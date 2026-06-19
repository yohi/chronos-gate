"""MCP SSE transport handlers."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from chronos_gate.approval.models import DecisionStatus
from chronos_gate.approval.notifier import (
    ApprovalNotifier,
    ApprovalRequest,
    LogOnlyApprovalNotifier,
)
from chronos_gate.approval.notifier import (
    sanitize_for_log as _sanitize_for_log,
)
from chronos_gate.approval.registry import PendingApprovalRegistry
from chronos_gate.approval.sanitize import sanitize_reason
from chronos_gate.audit.logger import AuditLogger
from chronos_gate.auth.api_key import ApiKeyAuthenticator
from chronos_gate.auth.handshake import HandshakeService
from chronos_gate.auth.session import SessionRegistry
from chronos_gate.errors import AuthError, PolicyError, SessionError, UpstreamError
from chronos_gate.filters.factory import build_filter
from chronos_gate.policy.engine import Grant, PolicyEngine
from chronos_gate.policy.models import GatewayPolicy
from chronos_gate.tools.proxy import ToolProxy, _contains_secret
from chronos_gate.tools.registry import ToolRegistry


def run_gateway() -> None:
    """Compatibility launcher kept until Task 3.5 rewires ``__main__``."""
    import uvicorn

    from chronos_gate.app import build_app
    from chronos_gate.config import GatewaySettings

    settings = GatewaySettings()
    uvicorn.run(build_app(), host=settings.host, port=settings.port, log_level="info")


async def _keep_alive() -> None:
    """Helper to keep the SSE connection alive. Monkeypatched in tests."""
    await asyncio.sleep(1)


async def _request_approval_with_isolation(
    *,
    approval_notifier: ApprovalNotifier,
    request: ApprovalRequest,
    audit: AuditLogger,
    sid: str,
    timeout: float = 5.0,
) -> None:
    try:
        await asyncio.wait_for(
            approval_notifier.request_approval(request),
            timeout=timeout,
        )
    # Non-critical notifier failures must not break the main request flow.
    # We swallow them after audit logging because notifier_exc is recorded via
    # audit.log(error_type=...) and the client has already received approval_required.
    except Exception as notifier_exc:  # noqa: BLE001 - deliberate isolation boundary
        audit.log(
            ev="notification_failed",
            detail="Approval notification failed",
            error_type=notifier_exc.__class__.__name__,
            sid=sid,
        )


def _schedule_approval_request(
    *,
    approval_notifier: ApprovalNotifier,
    request: ApprovalRequest,
    audit: AuditLogger,
    sid: str,
    timeout: float = 5.0,
) -> asyncio.Task[None]:
    return asyncio.create_task(
        _request_approval_with_isolation(
            approval_notifier=approval_notifier,
            request=request,
            audit=audit,
            sid=sid,
            timeout=timeout,
        )
    )


def _is_validation_deny(reason: str | None) -> bool:
    if reason is None:
        return False
    return reason.startswith("param_") or reason.startswith("forbidden_param:")


def _approval_id_for_log(approval_id: str) -> str:
    """Return the truncated, non-recoverable form of an approval_id for audit logging."""
    return approval_id[:8] + "..."


def _resolve_fallback_mode(value: str) -> Literal["allow", "ask"]:
    """Validate CHRONOS_EVALUATOR_FALLBACK and fall back to 'ask' on invalid values."""
    import logging as _logging

    _logger = _logging.getLogger("chronos_evaluator")
    if value == "ask":
        return "ask"
    if value == "allow":
        return "allow"
    _logger.warning(
        "Invalid CHRONOS_EVALUATOR_FALLBACK=%r, falling back to 'ask'",
        value,
    )
    return "ask"


async def _handle_sse(
    request: Request,
    *,
    handshake: HandshakeService,
    audit: AuditLogger,
) -> Any:
    try:
        record = handshake.handshake(
            authorization_header=request.headers.get("authorization"),
            intent_header=request.headers.get("x-mcp-intent"),
            requested_tools_header=request.headers.get("x-mcp-requested-tools"),
        )
    except AuthError as exc:
        audit.log(ev="handshake", decision="deny", reason="auth_failed", detail=str(exc))
        raise HTTPException(status_code=401, detail="auth_failed") from exc
    except PolicyError as exc:
        audit.log(
            ev="handshake",
            decision="deny",
            reason="policy_violation",
            detail=str(exc),
        )
        raise HTTPException(status_code=403, detail="policy_violation") from exc

    audit.log(
        ev="handshake",
        decision="allow",
        agent=record.agent_id,
        intent=record.intent,
        sid=record.session_id,
        caps=sorted(record.caps),
    )

    async def event_stream() -> Any:
        yield {"event": "endpoint", "data": f"/messages?session_id={record.session_id}"}
        try:
            while not await request.is_disconnected():
                await _keep_alive()
        except asyncio.CancelledError:
            pass

    return EventSourceResponse(event_stream(), ping=15)


def _jsonrpc_error(
    rpc_id: Any,
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "error": error})


async def _register_approval(
    *,
    approval_registry: PendingApprovalRegistry,
    record: Any,
    tool_name: str,
    arguments: dict[str, Any],
) -> str:
    return await approval_registry.register(
        session_id=record.session_id,
        requester_agent_id=record.agent_id,
        request=ApprovalRequest(
            session_id=record.session_id,
            approval_id="PENDING",
            agent_id=record.agent_id,
            intent=record.intent,
            tool_name=tool_name,
            arguments=_sanitize_for_log(arguments),
            requested_at=datetime.now(UTC),
        ),
    )


async def _handle_requires_approval_without_registry(
    *,
    rpc_id: Any,
    sid: str,
    record: Any,
    tool_name: str,
    arguments: dict[str, Any],
    audit: AuditLogger,
    approval_notifier: ApprovalNotifier,
) -> JSONResponse:
    request_payload = ApprovalRequest(
        session_id=record.session_id,
        approval_id="N/A",
        agent_id=record.agent_id,
        intent=record.intent,
        tool_name=tool_name,
        arguments=_sanitize_for_log(arguments),
        requested_at=datetime.now(UTC),
    )
    audit.log(
        ev="call",
        decision="requires_approval",
        agent=record.agent_id,
        sid=sid,
        tool=tool_name,
    )
    _schedule_approval_request(
        approval_notifier=approval_notifier,
        audit=audit,
        sid=sid,
        request=request_payload,
    )
    return _jsonrpc_error(
        rpc_id,
        -32001,
        "approval_required",
        {"session_id": record.session_id},
    )


async def _handle_requires_approval_with_registry(
    *,
    rpc_id: Any,
    sid: str,
    record: Any,
    tool_name: str,
    arguments: dict[str, Any],
    sessions: SessionRegistry,
    audit: AuditLogger,
    approval_notifier: ApprovalNotifier,
    approval_registry: PendingApprovalRegistry,
    approval_blocking_mode: bool,
    approval_timeout_seconds: float,
) -> tuple[JSONResponse | None, bool, str | None, Any]:
    try:
        approval_id = await _register_approval(
            approval_registry=approval_registry,
            record=record,
            tool_name=tool_name,
            arguments=arguments,
        )
    except PolicyError:
        audit.log(
            ev="call",
            decision="deny",
            reason="approval_registry_full",
            agent=record.agent_id,
            sid=sid,
            tool=tool_name,
        )
        return _jsonrpc_error(rpc_id, -32603, "internal_error"), False, None, record

    request_payload = ApprovalRequest(
        session_id=record.session_id,
        approval_id=approval_id,
        agent_id=record.agent_id,
        intent=record.intent,
        tool_name=tool_name,
        arguments=_sanitize_for_log(arguments),
        requested_at=datetime.now(UTC),
    )

    if not approval_blocking_mode:
        audit.log(
            ev="call",
            decision="requires_approval",
            agent=record.agent_id,
            sid=sid,
            tool=tool_name,
            approval_ref=_approval_id_for_log(approval_id),
        )
        _schedule_approval_request(
            approval_notifier=approval_notifier,
            audit=audit,
            sid=sid,
            request=request_payload,
        )
        return (
            _jsonrpc_error(
                rpc_id,
                -32001,
                "approval_required",
                {"session_id": record.session_id, "approval_id": approval_id},
            ),
            False,
            None,
            record,
        )

    approval_ref = _approval_id_for_log(approval_id)
    _schedule_approval_request(
        approval_notifier=approval_notifier,
        audit=audit,
        sid=sid,
        request=request_payload,
    )
    audit.log(
        ev="call",
        decision="approval_pending",
        agent=record.agent_id,
        sid=sid,
        tool=tool_name,
        approval_ref=approval_ref,
    )

    approval_decision = await approval_registry.wait_for_decision(
        approval_id,
        timeout=approval_timeout_seconds,
    )

    try:
        record = sessions.lookup(sid)
        sessions.touch(sid)
    except SessionError:
        audit.log(
            ev="message",
            decision="deny",
            reason="session_invalid_after_approval",
            sid=sid,
        )
        return (
            _jsonrpc_error(
                rpc_id,
                -32004,
                "session_expired",
                {"approval_id": approval_id},
            ),
            False,
            approval_ref,
            record,
        )

    if approval_decision.status is DecisionStatus.APPROVED:
        return None, True, approval_ref, record
    if approval_decision.status is DecisionStatus.REJECTED:
        audit.log(
            ev="call",
            decision="approval_rejected",
            agent=record.agent_id,
            sid=sid,
            tool=tool_name,
            approval_ref=approval_ref,
            reason=approval_decision.reason,
        )
        return (
            _jsonrpc_error(
                rpc_id,
                -32002,
                "approval_rejected",
                {"approval_id": approval_id},
            ),
            False,
            approval_ref,
            record,
        )

    audit.log(
        ev="call",
        decision="approval_timeout",
        agent=record.agent_id,
        sid=sid,
        tool=tool_name,
        approval_ref=approval_ref,
    )
    return (
        _jsonrpc_error(
            rpc_id,
            -32003,
            "approval_timeout",
            {"approval_id": approval_id},
        ),
        False,
        approval_ref,
        record,
    )


async def _handle_tool_call(
    *,
    rpc_id: Any,
    sid: str,
    record: Any,
    params: dict[str, Any],
    sessions: SessionRegistry,
    upstream: Any,
    policy: GatewayPolicy,
    audit: AuditLogger,
    engine: PolicyEngine,
    approval_notifier: ApprovalNotifier,
    approval_registry: PendingApprovalRegistry | None,
    approval_blocking_mode: bool,
    approval_timeout_seconds: float,
) -> JSONResponse:
    tool_name = params.get("name")
    if not tool_name:
        return _jsonrpc_error(rpc_id, -32602, "Invalid params: missing required parameter: name")

    if "arguments" in params:
        arguments = params["arguments"]
        if not isinstance(arguments, dict):
            return _jsonrpc_error(rpc_id, -32602, "Invalid params: 'arguments' must be an object")
    else:
        arguments = {}

    decision = engine.evaluate_call(
        grant=Grant(
            intent=record.intent,
            caps=record.caps,
            output_filter_profile=record.output_filter_profile,
            guardrails=record.guardrails,
        ),
        tool_name=tool_name,
        arguments=arguments,
    )
    was_approved = False
    approval_ref: str | None = None

    match decision.status:
        case "DENY":
            audit.log(
                ev="call",
                decision="deny",
                reason=decision.reason,
                agent=record.agent_id,
                sid=sid,
                tool=tool_name,
            )
            error = (
                {"code": -32602, "message": decision.reason}
                if _is_validation_deny(decision.reason)
                else {"code": -32601, "message": "tool not found"}
            )
            return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "error": error})
        case "ALLOW" | "REQUIRES_APPROVAL" if _contains_secret(arguments):
            audit.log(
                ev="call",
                decision="deny",
                reason="secret_in_approval_args",
                agent=record.agent_id,
                sid=sid,
                tool=tool_name,
            )
            return _jsonrpc_error(rpc_id, -32601, "tool not found")
        case "REQUIRES_APPROVAL":
            if approval_blocking_mode and approval_registry is None:
                raise RuntimeError("approval_registry precondition was not enforced")
            if approval_registry is None:
                return await _handle_requires_approval_without_registry(
                    rpc_id=rpc_id,
                    sid=sid,
                    record=record,
                    tool_name=tool_name,
                    arguments=arguments,
                    audit=audit,
                    approval_notifier=approval_notifier,
                )
            approval_response, was_approved, approval_ref, record = (
                await _handle_requires_approval_with_registry(
                    rpc_id=rpc_id,
                    sid=sid,
                    record=record,
                    tool_name=tool_name,
                    arguments=arguments,
                    sessions=sessions,
                    audit=audit,
                    approval_notifier=approval_notifier,
                    approval_registry=approval_registry,
                    approval_blocking_mode=approval_blocking_mode,
                    approval_timeout_seconds=approval_timeout_seconds,
                )
            )
            if approval_response is not None:
                return approval_response
        case "ALLOW":
            pass

    if record.output_filter_profile not in policy.output_filters:
        audit.log(
            ev="call",
            decision="deny",
            reason="filter_profile_not_found",
            sid=sid,
            profile=record.output_filter_profile,
        )
        return _jsonrpc_error(rpc_id, -32603, "output_filter_profile_not_found")

    filter_ = build_filter(policy.output_filters[record.output_filter_profile])
    proxy = ToolProxy(upstream=upstream, filter_=filter_)
    try:
        payload = await proxy._call_server_trusted(
            tool_name=tool_name,
            arguments=arguments,
        )
    except PolicyError as exc:
        audit.log(
            ev="call",
            decision="deny",
            reason="sanitize",
            agent=record.agent_id,
            sid=sid,
            tool=tool_name,
        )
        return _jsonrpc_error(rpc_id, -32602, str(exc))
    except UpstreamError:
        audit.log(
            ev="call",
            decision="upstream_error",
            agent=record.agent_id,
            sid=sid,
            tool=tool_name,
        )
        return _jsonrpc_error(rpc_id, -32000, "upstream_error")

    audit_kwargs = {
        "ev": "call",
        "decision": "allow_after_approval" if was_approved else "allow",
        "agent": record.agent_id,
        "sid": sid,
        "tool": tool_name,
    }
    if was_approved and approval_ref is not None:
        audit_kwargs["approval_ref"] = approval_ref
    audit.log(**audit_kwargs)
    return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": payload})


async def _handle_messages(
    request: Request,
    *,
    sessions: SessionRegistry,
    tool_registry: ToolRegistry,
    upstream: Any,
    policy: GatewayPolicy,
    audit: AuditLogger,
    engine: PolicyEngine,
    approval_notifier: ApprovalNotifier,
    approval_registry: PendingApprovalRegistry | None,
    approval_blocking_mode: bool,
    approval_timeout_seconds: float,
) -> Any:
    sid = request.query_params.get("session_id", "")
    try:
        record = sessions.lookup(sid)
    except SessionError as exc:
        audit.log(ev="message", decision="deny", reason="session_invalid", sid=sid)
        raise HTTPException(status_code=404, detail="session_invalid") from exc

    sessions.touch(sid)
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        return _jsonrpc_error(None, -32700, f"Parse error: {exc}")

    if not isinstance(body, dict):
        return _jsonrpc_error(None, -32600, "Invalid Request: body must be an object")

    method = body.get("method")
    rpc_id = body.get("id")
    if method == "tools/list":
        tools = tool_registry.filter_by_caps(caps=record.caps)
        return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": tools}})

    if method == "tools/call":
        params = body.get("params")
        if not isinstance(params, dict):
            return _jsonrpc_error(rpc_id, -32602, "Invalid params: 'params' must be an object")
        return await _handle_tool_call(
            rpc_id=rpc_id,
            sid=sid,
            record=record,
            params=params,
            sessions=sessions,
            upstream=upstream,
            policy=policy,
            audit=audit,
            engine=engine,
            approval_notifier=approval_notifier,
            approval_registry=approval_registry,
            approval_blocking_mode=approval_blocking_mode,
            approval_timeout_seconds=approval_timeout_seconds,
        )

    return _jsonrpc_error(rpc_id, -32601, f"unknown method {method!r}")


async def _handle_approvals(
    request: Request,
    *,
    policy: GatewayPolicy,
    audit: AuditLogger,
    approval_registry: PendingApprovalRegistry,
    api_authenticator: ApiKeyAuthenticator,
) -> Any:
    authz = request.headers.get("authorization") or ""
    scheme, _, raw = authz.partition(" ")
    if scheme.lower() != "bearer" or not raw:
        return JSONResponse({"error": "auth_failed"}, status_code=401)

    try:
        resolver_agent_id = api_authenticator.authenticate(raw)
    except AuthError:
        return JSONResponse({"error": "auth_failed"}, status_code=401)

    raw_body = bytearray()
    async for chunk in request.stream():
        raw_body.extend(chunk)
        if len(raw_body) > 1024:
            return JSONResponse({"error": "payload_too_large"}, status_code=413)
    try:
        body = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "invalid_request"}, status_code=400)

    approval_id = body.get("approval_id")
    raw_decision = body.get("decision")
    if (
        not isinstance(approval_id, str)
        or len(approval_id) != 32
        or not all(c in "0123456789abcdef" for c in approval_id)
        or raw_decision not in {"approve", "reject"}
    ):
        return JSONResponse({"error": "invalid_request"}, status_code=400)

    requester_id = await approval_registry.get_requester_agent_id(approval_id)
    if requester_id is not None and requester_id == resolver_agent_id:
        audit.log(
            ev="approval_decision",
            outcome="self_approval",
            resolver=resolver_agent_id,
            approval_ref=_approval_id_for_log(approval_id),
        )
        return JSONResponse({"error": "self_approval_forbidden"}, status_code=403)

    if policy.approvers and resolver_agent_id not in policy.approvers:
        audit.log(
            ev="approval_decision",
            outcome="forbidden_role",
            resolver=resolver_agent_id,
            approval_id="unknown",
        )
        return JSONResponse({"error": "forbidden"}, status_code=403)

    raw_reason = body.get("reason")
    if raw_reason is not None and not isinstance(raw_reason, str):
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    normalized_reason = sanitize_reason(raw_reason)
    status = DecisionStatus.APPROVED if raw_decision == "approve" else DecisionStatus.REJECTED
    outcome = await approval_registry.resolve(
        approval_id,
        resolver_agent_id=resolver_agent_id,
        status=status,
        reason=normalized_reason,
    )

    audit_fields: dict[str, Any] = {
        "outcome": outcome.value,
        "resolver": resolver_agent_id,
        "approval_ref": _approval_id_for_log(approval_id),
    }
    if normalized_reason is not None:
        audit_fields["reason"] = normalized_reason
    audit.log(ev="approval_decision", **audit_fields)

    if outcome.value == "ok":
        return JSONResponse(
            {"status": "resolved", "approval_id": approval_id},
            status_code=200,
        )
    if outcome.value == "forbidden":
        return JSONResponse({"error": "self_approval_forbidden"}, status_code=403)
    return JSONResponse({"error": "approval_not_found"}, status_code=404)


async def _handle_evaluate_call(
    request: Request,
    *,
    api_authenticator: ApiKeyAuthenticator | None,
    shared_evaluator: Any,
) -> Any:
    import logging

    from pydantic import ValidationError

    from chronos_gate.errors import AuthError
    from chronos_gate.policy.models_evaluator import ToolCallInput

    logger = logging.getLogger("chronos_gate.server")

    if api_authenticator is not None:
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            raise HTTPException(status_code=401, detail="Missing Authorization header")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="Invalid Authorization scheme; must be Bearer",
            )
        token = auth_header[7:].strip()
        try:
            api_authenticator.authenticate(token)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")

    tool_name = body.get("tool_name")
    tool_input = body.get("tool_input", {})
    context = body.get("context", {})

    if not isinstance(tool_name, str) or not tool_name:
        raise HTTPException(status_code=400, detail="tool_name is required and must be a string")
    if not isinstance(tool_input, dict):
        raise HTTPException(status_code=400, detail="tool_input must be a JSON object")
    if not isinstance(context, dict):
        raise HTTPException(status_code=400, detail="context must be a JSON object")

    try:
        input_ = ToolCallInput(
            tool_name=tool_name,
            tool_input=tool_input,
            context=context,
        )
        decision = await shared_evaluator.evaluate(input_)
        return decision.to_dict()
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error during evaluation")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


async def _handle_healthz() -> dict[str, str]:
    return {"status": "ok"}


def build_router(
    *,
    handshake: HandshakeService,
    sessions: SessionRegistry,
    tool_registry: ToolRegistry,
    upstream: Any,
    policy: GatewayPolicy,
    audit: AuditLogger,
    engine: PolicyEngine,
    approval_notifier: ApprovalNotifier | None = None,
    approval_registry: PendingApprovalRegistry | None = None,
    approval_blocking_mode: bool = False,
    approval_timeout_seconds: float = 30.0,
    api_authenticator: ApiKeyAuthenticator | None = None,
) -> APIRouter:
    if approval_blocking_mode and approval_registry is None:
        raise ValueError("approval_registry must be provided when approval_blocking_mode=True")
    if approval_registry is not None and api_authenticator is None:
        raise ValueError("api_authenticator must be provided when approval_registry is provided")
    if approval_blocking_mode and approval_timeout_seconds <= 0:
        raise ValueError("approval_timeout_seconds must be positive")

    import os

    from chronos_gate.policy.composite import CompositeEvaluator
    from chronos_gate.policy.llm_evaluator import LlmEvaluator
    from chronos_gate.policy.memory_client import MemoryClient

    shared_evaluator = CompositeEvaluator(
        engine=engine,
        memory_client=MemoryClient.from_env(),
        llm_evaluator=LlmEvaluator.from_env(),
        default_intent=os.getenv("CHRONOS_EVALUATOR_DEFAULT_INTENT", "default"),
        default_agent_id=os.getenv("CHRONOS_EVALUATOR_DEFAULT_AGENT_ID", "claude-code"),
        fallback_when_llm_not_configured=_resolve_fallback_mode(
            os.getenv("CHRONOS_EVALUATOR_FALLBACK", "ask"),
        ),
    )

    router = APIRouter()
    if approval_notifier is None:
        approval_notifier = LogOnlyApprovalNotifier()

    @router.get(
        "/sse",
        responses={
            401: {"description": "Authentication failed"},
            403: {"description": "Policy violation"},
        },
    )
    async def sse(request: Request) -> Any:
        return await _handle_sse(request, handshake=handshake, audit=audit)

    @router.post(
        "/messages",
        responses={
            404: {"description": "Session invalid or expired"},
        },
    )
    async def messages(request: Request) -> Any:
        return await _handle_messages(
            request,
            sessions=sessions,
            tool_registry=tool_registry,
            upstream=upstream,
            policy=policy,
            audit=audit,
            engine=engine,
            approval_notifier=approval_notifier,
            approval_registry=approval_registry,
            approval_blocking_mode=approval_blocking_mode,
            approval_timeout_seconds=approval_timeout_seconds,
        )

    if approval_registry is not None:
        if api_authenticator is None:
            raise RuntimeError("api_authenticator precondition was not enforced")

        @router.post("/approvals")
        async def approvals(request: Request) -> Any:
            return await _handle_approvals(
                request,
                policy=policy,
                audit=audit,
                approval_registry=approval_registry,
                api_authenticator=api_authenticator,
            )

    @router.post(
        "/evaluate",
        responses={
            400: {"description": "Invalid request body or parameters"},
            401: {"description": "Missing or invalid Authorization header"},
            500: {"description": "Internal server error"},
        },
    )
    async def evaluate_call(request: Request) -> Any:
        return await _handle_evaluate_call(
            request,
            api_authenticator=api_authenticator,
            shared_evaluator=shared_evaluator,
        )

    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        return await _handle_healthz()

    return router


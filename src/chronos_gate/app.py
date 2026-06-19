"""FastAPI app factory."""

from __future__ import annotations

import json
import logging
import os
import sys
from contextlib import asynccontextmanager

if sys.version_info >= (3, 9):
    from importlib.resources import as_file, files  # nosemgrep: python.lang.compatibility.python37.python37-compatibility-importlib2
else:
    from importlib_resources import as_file, files
from typing import Any, AsyncContextManager, AsyncGenerator, Callable, Coroutine

from fastapi import FastAPI
from pydantic import ValidationError

from chronos_gate.approval.notifier import LogOnlyApprovalNotifier
from chronos_gate.approval.registry import PendingApprovalRegistry
from chronos_gate.audit.logger import AuditLogger
from chronos_gate.auth.api_key import ApiKeyAuthenticator
from chronos_gate.auth.handshake import HandshakeService
from chronos_gate.auth.session import InMemorySessionRegistry
from chronos_gate.config import GatewaySettings
from chronos_gate.middleware import MaxBodySizeMiddleware
from chronos_gate.policy.engine import PolicyEngine
from chronos_gate.policy.loader import load_policy
from chronos_gate.policy.models import GatewayPolicy
from chronos_gate.server import build_router
from chronos_gate.tools.registry import ToolRegistry


def _decode_keys(settings: GatewaySettings) -> dict[str, str]:
    if settings.api_keys_json is None:
        return {}
    raw = settings.api_keys_json.get_secret_value()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in api_keys_json: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError(f"api_keys_json must be a JSON object, got {type(parsed).__name__}")

    decoded: dict[str, str] = {}
    for k, v in parsed.items():
        if not isinstance(k, str) or not k:
            raise ValueError(f"API key must be a non-empty string, got {k!r}")
        if not isinstance(v, str) or not v:
            raise ValueError(f"API key value must be a non-empty string for agent {k!r}")
        decoded[k] = v
    return decoded


def _is_missing_policy_path_error(exc: ValidationError) -> bool:
    return any(
        error.get("loc") == ("policy_path",) and error.get("type") == "missing"
        for error in exc.errors()
    )


def _load_sample_policy() -> tuple[GatewaySettings, GatewayPolicy]:
    resource = files("chronos_gate").joinpath("policies/intents.example.yaml")
    with as_file(resource) as sample_policy:
        settings = GatewaySettings(policy_path=sample_policy)
        return settings, load_policy(settings.policy_path)


def _load_settings_and_policy(
    upstream_override: Any | None,
) -> tuple[GatewaySettings, GatewayPolicy]:
    try:
        settings = GatewaySettings()
        return settings, load_policy(settings.policy_path)
    except ValidationError as exc:
        if upstream_override is None or not _is_missing_policy_path_error(exc):
            raise
        return _load_sample_policy()


def _build_session_eviction_handler(
    *, approval_registry: PendingApprovalRegistry, audit: AuditLogger
) -> Callable[[str, str], Coroutine[Any, Any, None]]:
    async def _on_session_evicted(sid: str, reason: str) -> None:
        try:
            await approval_registry.cancel_session(sid, reason=reason)
        except Exception as exc:
            audit.log(
                ev="session_evict_failed",
                error_type=exc.__class__.__name__,
                sid=sid,
                reason=reason,
            )
            raise

    return _on_session_evicted


def _build_upstream(settings: GatewaySettings, upstream_override: Any | None) -> Any:
    if upstream_override is not None:
        return upstream_override

    from chronos_gate.upstream.context_store_client import UpstreamClient, build_upstream_env

    return UpstreamClient(
        command=settings.upstream_command,
        env=build_upstream_env(
            passthrough=settings.upstream_env_passthrough,
            base_env=dict(os.environ),
        ),
    )


def _hidden_tools_for_ingestion_mode(settings: GatewaySettings) -> frozenset[str]:
    if settings.ingestion_mode != "all":
        return frozenset()

    logging.getLogger(__name__).warning(
        "ingestion mode: all - 'memory_save' tool is HIDDEN from agents. "
        "Client-side hook (e.g. scripts/agent_turn_hook.py via Stop event) "
        "MUST be configured to send conversation logs at turn end. "
        "See README.md §Hybrid Ingestion Mode for client-specific setup."
    )
    return frozenset({"memory_save"})


def _build_lifespan(
    *, upstream: Any, upstream_override: Any | None, registry: ToolRegistry
) -> Callable[[FastAPI], AsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        started = False
        try:
            # Start upstream only if not overridden
            if upstream_override is None:
                await upstream.start()
                started = True

            # Initialize or update tool registry on startup
            if hasattr(upstream, "list_tools"):
                all_tools = await upstream.list_tools()
                registry.replace_tools(all_tools)

            yield
        finally:
            if upstream_override is None and started and hasattr(upstream, "stop"):
                await upstream.stop()

    return lifespan


def _attach_app_state(
    *,
    app: FastAPI,
    registry: ToolRegistry,
    approval_registry: PendingApprovalRegistry,
    sessions: InMemorySessionRegistry,
) -> None:
    app.state.tool_registry = registry
    app.state.approval_registry = approval_registry
    app.state.sessions = sessions


def build_app(
    *, upstream_override: Any | None = None, initial_tools: list[dict[str, Any]] | None = None
) -> FastAPI:
    settings, policy = _load_settings_and_policy(upstream_override)
    audit = AuditLogger(level=settings.audit_log_level)
    auth = ApiKeyAuthenticator(_decode_keys(settings))
    engine = PolicyEngine(policy)
    approval_registry = PendingApprovalRegistry(max_pending=settings.approval_max_pending)

    sessions = InMemorySessionRegistry(
        ttl_seconds=settings.session_ttl_seconds,
        idle_timeout_seconds=settings.session_idle_timeout_seconds,
        on_session_evicted=_build_session_eviction_handler(
            approval_registry=approval_registry,
            audit=audit,
        ),
    )
    handshake = HandshakeService(
        authenticator=auth,
        policy_engine=engine,
        session_registry=sessions,
    )

    upstream = _build_upstream(settings, upstream_override)

    hidden_tools = _hidden_tools_for_ingestion_mode(settings)
    registry = ToolRegistry(initial_tools or [], hidden_tools=hidden_tools)

    lifespan = _build_lifespan(
        upstream=upstream,
        upstream_override=upstream_override,
        registry=registry,
    )
    app = FastAPI(title="ChronosGraph MCP Gateway", lifespan=lifespan)
    app.add_middleware(MaxBodySizeMiddleware, max_size_bytes=settings.max_request_body_size_bytes)
    _attach_app_state(
        app=app,
        registry=registry,
        approval_registry=approval_registry,
        sessions=sessions,
    )

    app.include_router(
        build_router(
            handshake=handshake,
            sessions=sessions,
            tool_registry=registry,
            upstream=upstream,
            policy=policy,
            audit=audit,
            engine=engine,
            approval_notifier=LogOnlyApprovalNotifier(),
            approval_registry=approval_registry if settings.approval_blocking_mode else None,
            approval_blocking_mode=settings.approval_blocking_mode,
            approval_timeout_seconds=settings.approval_timeout_seconds,
            api_authenticator=auth,
        )
    )

    return app

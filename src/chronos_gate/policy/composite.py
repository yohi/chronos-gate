"""CompositeEvaluator: Tier 1 (deterministic PolicyEngine) + Tier 2 (LLM)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Literal

from ..errors import PolicyError
from ._composite_llm import evaluate_with_llm
from .engine import Grant, PolicyEngine
from .llm_evaluator import (
    READ_ONLY_TOOLS,
    LlmEvaluator,
)
from .memory_client import MemoryClient, MemoryFetchError
from .models_evaluator import (
    Decision,
    MemoryItem,
    ToolCallInput,
    summarize_tool_input,
)

logger = logging.getLogger("chronos_evaluator")


class CompositeEvaluator:
    def __init__(
        self,
        *,
        engine: PolicyEngine,
        memory_client: MemoryClient | None,
        llm_evaluator: LlmEvaluator | None,
        default_intent: str = "default",
        default_agent_id: str = "claude-code",
        fallback_when_llm_not_configured: Literal["allow", "ask"] = "ask",
        evaluation_cache_ttl_seconds: float = 300.0,
        memory_timeout_seconds: float = 3.0,
    ) -> None:
        self._engine: PolicyEngine = engine
        self._memory: MemoryClient | None = memory_client
        self._llm: LlmEvaluator | None = llm_evaluator
        self._default_intent: str = default_intent
        self._default_agent_id: str = default_agent_id
        if fallback_when_llm_not_configured not in {"allow", "ask"}:
            invalid_fallback = fallback_when_llm_not_configured
            raise ValueError(
                f"fallback_when_llm_not_configured must be allow/ask, got {invalid_fallback!r}"
            )
        self._fallback: Literal["allow", "ask"] = fallback_when_llm_not_configured
        if memory_timeout_seconds <= 0:
            raise ValueError(f"memory_timeout_seconds must be > 0, got {memory_timeout_seconds}")
        self._evaluation_cache_ttl_seconds: float = evaluation_cache_ttl_seconds
        self._memory_timeout_seconds: float = memory_timeout_seconds
        self._decision_cache: dict[str, tuple[float, Decision]] = {}
        self._last_cleanup_time: float = time.monotonic()
        self._cache_cleanup_interval: float = 60.0  # seconds
        self._in_flight_judgments: dict[str, asyncio.Future[Decision]] = {}

        logger.warning(
            "evaluator config: llm=%s memory=%s fallback_when_llm_not_configured=%s",
            "enabled" if llm_evaluator is not None else "DISABLED",
            "enabled" if memory_client is not None else "disabled",
            self._fallback,
        )
        if llm_evaluator is None and self._fallback == "allow":
            msg = (
                "evaluator config: llm=DISABLED fallback=allow - "
                "tools will be auto-approved without LLM review"
            )
            logger.warning(msg)

    async def evaluate(self, input_: ToolCallInput) -> Decision:
        intent, agent_id = self._resolve_request_context(input_)
        grant_result = self._evaluate_grant(intent=intent, agent_id=agent_id)
        if isinstance(grant_result, Decision):
            return grant_result

        tier1_decision = self._evaluate_tier1_call(input_, grant_result)
        if tier1_decision is not None:
            return tier1_decision

        llm_short_circuit = self._decision_before_llm(input_, grant_result)
        if llm_short_circuit is not None:
            return llm_short_circuit

        if self._llm is None:
            return self._decision_without_llm()
        return await evaluate_with_llm(
            self,
            input_,
            grant_result,
            intent,
            agent_id,
            self._llm,
        )

    def _resolve_request_context(self, input_: ToolCallInput) -> tuple[str, str]:
        intent = str(input_.context.get("intent") or self._default_intent)
        agent_id = str(input_.context.get("agent_id") or self._default_agent_id)
        return intent, agent_id

    def _evaluate_grant(self, *, intent: str, agent_id: str) -> Grant | Decision:
        try:
            return self._engine.evaluate_grant(
                agent_id=agent_id,
                intent=intent,
                requested_tools=None,
            )
        except PolicyError as exc:
            return Decision(verdict="deny", reason=(exc.reason or "policy_violation"))

    def _evaluate_tier1_call(self, input_: ToolCallInput, grant: Grant) -> Decision | None:
        try:
            tier1 = self._engine.evaluate_call(
                grant=grant,
                tool_name=input_.tool_name,
                arguments=input_.tool_input,
            )
        except PolicyError as exc:
            return Decision(verdict="deny", reason=(exc.reason or "policy_violation"))
        return self._decision_from_tier1(input_, tier1)

    @staticmethod
    def _decision_from_tier1(input_: ToolCallInput, tier1: object) -> Decision | None:
        status = getattr(tier1, "status", None)
        reason = getattr(tier1, "reason", None)
        if status == "DENY":
            return Decision(verdict="deny", reason=(reason or "guardrail_violation"))
        if status == "REQUIRES_APPROVAL":
            return Decision(
                verdict="ask",
                ask_message=f"Tool {input_.tool_name!r} requires manual approval.",
            )
        if status == "ALLOW":
            return None

        logger.warning(
            "Unexpected tier1 status %r for tool %r; treating as deny",
            status,
            input_.tool_name,
        )
        return Decision(verdict="deny", reason="unexpected_evaluation_status")

    def _decision_before_llm(self, input_: ToolCallInput, grant: Grant) -> Decision | None:
        if self._should_skip_llm(input_, grant):
            return Decision(verdict="allow")
        if input_.tool_name in READ_ONLY_TOOLS:
            return Decision(verdict="allow")
        if self._llm is None:
            return self._decision_without_llm()
        return None

    @staticmethod
    def _should_skip_llm(input_: ToolCallInput, grant: Grant) -> bool:
        guardrail = grant.guardrails.get(input_.tool_name)
        return guardrail is not None and guardrail.skip_llm

    def _decision_without_llm(self) -> Decision:
        if self._fallback == "ask":
            return Decision(
                verdict="ask",
                ask_message="LLM evaluator is not configured; human confirmation required.",
            )
        return Decision(verdict="allow")

    async def _fetch_memories_safely(self, input_: ToolCallInput) -> list[MemoryItem]:
        if self._memory is None:
            return []

        query = f"tool:{input_.tool_name} " + summarize_tool_input(input_.tool_input)
        project = str(input_.context.get("project") or "")
        try:
            return await asyncio.wait_for(
                self._memory.retrieve(query=query, project=project or None),
                timeout=self._memory_timeout_seconds,
            )
        except (asyncio.TimeoutError, MemoryFetchError) as exc:
            logger.warning("memory fetch failed (continuing without memory): %s", exc)
            return []

    def _get_cached_decision(self, cache_key: str) -> Decision | None:
        cached = self._decision_cache.get(cache_key)
        if cached is None:
            return None
        expires_at, decision = cached
        if expires_at <= time.monotonic():
            _ = self._decision_cache.pop(cache_key, None)
            return None
        return decision

    def _store_cached_decision(self, cache_key: str, decision: Decision) -> None:
        if self._evaluation_cache_ttl_seconds <= 0:
            return
        expires_at = time.monotonic() + self._evaluation_cache_ttl_seconds
        self._decision_cache[cache_key] = (expires_at, decision)

    def _maybe_cleanup_cache(self) -> None:
        """一定時間経過していたら期限切れキャッシュを掃除する。"""
        now = time.monotonic()
        if now - self._last_cleanup_time < self._cache_cleanup_interval:
            return
        self._last_cleanup_time = now
        self._cleanup_expired_decisions()

    def _cleanup_expired_decisions(self) -> None:
        """期限切れのエントリをすべて削除する。"""
        now = time.monotonic()
        expired_keys = [
            k for k, (expires_at, _) in self._decision_cache.items() if expires_at <= now
        ]
        for k in expired_keys:
            self._decision_cache.pop(k, None)
        if expired_keys:
            logger.debug("Cleaned up %d expired cache entries", len(expired_keys))

    def _make_decision_cache_key(
        self,
        input_: ToolCallInput,
        intent: str,
        agent_id: str,
    ) -> str:
        payload = {
            "agent_id": agent_id,
            "intent": intent,
            "llm_model": getattr(self._llm, "_model", None),
            "project": str(input_.context.get("project") or ""),
            "tool_input": input_.tool_input,
            "tool_name": input_.tool_name,
        }
        raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

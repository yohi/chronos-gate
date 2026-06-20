from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from .engine import Grant
from .llm_evaluator import LlmEvaluator, LlmUnavailableError, ResponseParseError
from .models_evaluator import Decision, MemoryItem, ToolCallInput

logger = logging.getLogger("chronos_evaluator")

_FALLBACK_ASK_MESSAGE = "System evaluation failed. Human confirmation required."


class _CompositeEvaluatorState(Protocol):
    _in_flight_judgments: dict[str, asyncio.Future[Decision]]

    def _maybe_cleanup_cache(self) -> None: ...

    def _make_decision_cache_key(
        self,
        input_: ToolCallInput,
        intent: str,
        agent_id: str,
    ) -> str: ...

    def _get_cached_decision(self, cache_key: str) -> Decision | None: ...

    def _store_cached_decision(self, cache_key: str, decision: Decision) -> None: ...

    async def _fetch_memories_safely(self, input_: ToolCallInput) -> list[MemoryItem]: ...


async def evaluate_with_llm(
    state: _CompositeEvaluatorState,
    input_: ToolCallInput,
    grant: Grant,
    intent: str,
    agent_id: str,
    llm: LlmEvaluator,
) -> Decision:
    state._maybe_cleanup_cache()
    cache_key = state._make_decision_cache_key(input_, intent, agent_id)
    cached = state._get_cached_decision(cache_key)
    if cached is not None:
        return cached

    return await _judge_with_coalescing(state, input_, grant, intent, cache_key, llm)


async def _judge_with_coalescing(
    state: _CompositeEvaluatorState,
    input_: ToolCallInput,
    grant: Grant,
    intent: str,
    cache_key: str,
    llm: LlmEvaluator,
) -> Decision:
    if cache_key in state._in_flight_judgments:
        logger.info("Found in-flight judgment for key %s, waiting for result", cache_key)
        return await asyncio.shield(state._in_flight_judgments[cache_key])

    loop = asyncio.get_running_loop()
    fut: asyncio.Future[Decision] = loop.create_future()
    state._in_flight_judgments[cache_key] = fut
    try:
        return await _judge_and_publish(state, input_, grant, intent, cache_key, llm, fut)
    finally:
        state._in_flight_judgments.pop(cache_key, None)


async def _judge_and_publish(
    state: _CompositeEvaluatorState,
    input_: ToolCallInput,
    grant: Grant,
    intent: str,
    cache_key: str,
    llm: LlmEvaluator,
    fut: asyncio.Future[Decision],
) -> Decision:
    try:
        decision = await _judge_with_memories(state, input_, grant, intent, llm)
        state._store_cached_decision(cache_key, decision)
        _set_future_result(fut, decision)
        return decision
    except (LlmUnavailableError, ResponseParseError) as exc:
        return _fallback_from_llm_error(exc, fut)
    except Exception as exc:
        _set_future_exception(fut, exc)
        raise exc
    except BaseException as exc:
        _set_future_exception(fut, exc)
        raise


async def _judge_with_memories(
    state: _CompositeEvaluatorState,
    input_: ToolCallInput,
    grant: Grant,
    intent: str,
    llm: LlmEvaluator,
) -> Decision:
    memories = await state._fetch_memories_safely(input_)
    rules = _render_rules_for_prompt(grant, input_.tool_name)
    return await llm.judge(
        input_=input_,
        rules=rules,
        memories=memories,
        intent_name=intent,
    )


def _render_rules_for_prompt(grant: Grant, tool_name: str) -> str:
    guardrail = grant.guardrails.get(tool_name)
    if guardrail is None:
        return f"- intent={grant.intent}: no specific guardrails for tool {tool_name}."

    lines: list[str] = [f"- intent={grant.intent}, tool={tool_name}"]
    for param, constraint in guardrail.params.items():
        bits: list[str] = []
        if constraint.forbidden:
            bits.append("FORBIDDEN")
        if constraint.type:
            bits.append(f"type={constraint.type}")
        if constraint.max_length is not None:
            bits.append(f"max_length={constraint.max_length}")
        if constraint.pattern:
            bits.append(f"pattern={constraint.pattern!r}")
        if constraint.allowed_values:
            bits.append(f"allowed_values={constraint.allowed_values}")
        lines.append(f"  - {param}: {', '.join(bits) or '(no constraints)'}")

    if guardrail.requires_approval:
        lines.append("  - requires_approval=true")
    return "\n".join(lines)


def _set_future_result(fut: asyncio.Future[Decision], decision: Decision) -> None:
    if not fut.done():
        fut.set_result(decision)


def _set_future_exception(fut: asyncio.Future[Decision], exc: BaseException) -> None:
    if not fut.done():
        fut.set_exception(exc)


def _fallback_from_llm_error(
    exc: LlmUnavailableError | ResponseParseError,
    fut: asyncio.Future[Decision],
) -> Decision:
    logger.warning("Tier-2 fallback to ask: %s", exc)
    fallback_decision = Decision(verdict="ask", ask_message=_FALLBACK_ASK_MESSAGE)
    _set_future_result(fut, fallback_decision)
    return fallback_decision

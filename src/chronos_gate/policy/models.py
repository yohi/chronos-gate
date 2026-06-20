"""Pydantic models for intents.yaml.

References are validated post-parse (`_verify_references`) so the gateway refuses
to start with a malformed policy (Fail-fast / Default Deny).
"""

from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StructuralAllowlistSchema(BaseModel):
    # フィールド名 = True | list[str] (ネストの allowlist)
    # 動的キーを許すため extra="allow"。タイポ検出は GatewayPolicy._verify_references で実施。
    model_config = ConfigDict(extra="allow")


class OutputFilterDef(BaseModel):
    type: Literal["none", "structural_allowlist"]
    schemas: dict[str, StructuralAllowlistSchema] | None = None


MAX_PARAM_LENGTH = 1048576  # 1MB
MAX_PATTERN_LENGTH = 200
RE_DOS_MAX_LENGTH = 4096
ParamType = Literal["string", "integer", "number", "boolean"]


class ParamConstraint(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: ParamType | None = None
    max_length: int | None = None
    pattern: str | None = None
    allowed_values: list[str | int | float | bool] | None = None
    forbidden: bool = False

    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
        _validate_string_only_fields(self.type, self.pattern, self.max_length)
        _validate_allowed_values(self.type, self.allowed_values)
        _validate_pattern(self.pattern, self.max_length)
        _validate_max_length(self.max_length)
        return self


class ToolGuardrail(BaseModel):
    model_config = ConfigDict(frozen=True)
    params: dict[str, ParamConstraint] = Field(default_factory=dict)
    requires_approval: bool = False
    skip_llm: bool = False


class IntentPolicy(BaseModel):
    description: str
    allowed_tools: list[str] = Field(..., min_length=1)
    output_filter: str
    guardrails: dict[str, ToolGuardrail] = Field(default_factory=dict)


class AgentPolicy(BaseModel):
    allowed_intents: list[str]


class GatewayPolicy(BaseModel):
    version: Literal[1]
    output_filters: dict[str, OutputFilterDef]
    intents: dict[str, IntentPolicy]
    agents: dict[str, AgentPolicy]
    approvers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _verify_references(self) -> Self:
        _verify_intent_references(self.intents, self.output_filters)
        _verify_agent_intents(self.agents, self.intents)
        _verify_structural_allowlist_requires_schemas(self.output_filters)
        _verify_structural_allowlist_schema_keys(self.output_filters, self.intents)
        return self


def _validate_string_only_fields(
    param_type: ParamType | None,
    pattern: str | None,
    max_length: int | None,
) -> None:
    if param_type in (None, "string"):
        return
    if pattern is not None:
        raise ValueError(f"pattern is only allowed for type='string', got type={param_type!r}")
    if max_length is not None:
        raise ValueError(f"max_length is only allowed for type='string', got type={param_type!r}")


def _validate_allowed_values(
    param_type: ParamType | None,
    allowed_values: list[str | int | float | bool] | None,
) -> None:
    if allowed_values is None:
        return
    if not allowed_values:
        raise ValueError("allowed_values cannot be empty if specified")
    if param_type is None:
        _validate_homogeneous_allowed_values(allowed_values)
        return
    _validate_typed_allowed_values(param_type, allowed_values)


def _validate_typed_allowed_values(
    param_type: ParamType,
    allowed_values: list[str | int | float | bool],
) -> None:
    types_map: dict[ParamType, type | tuple[type, ...]] = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
    }
    expected_type = types_map[param_type]
    for value in allowed_values:
        _validate_allowed_value_type(param_type, expected_type, value)


def _validate_allowed_value_type(
    param_type: ParamType,
    expected_type: type | tuple[type, ...],
    value: str | int | float | bool,
) -> None:
    if param_type in ("integer", "number") and isinstance(value, bool):
        raise ValueError(f"allowed_values must be {param_type}, got boolean")
    if not isinstance(value, expected_type):
        raise ValueError(f"allowed_values must be {param_type}, got {type(value).__name__}")


def _validate_homogeneous_allowed_values(allowed_values: list[str | int | float | bool]) -> None:
    first_type = type(allowed_values[0])
    for value in allowed_values:
        if type(value) is not first_type:
            raise ValueError(
                f"allowed_values must be homogeneous when type is None, "
                f"got mixture of {first_type.__name__} and {type(value).__name__}"
            )


def _validate_pattern(pattern: str | None, max_length: int | None) -> None:
    if pattern is None:
        return
    if max_length is None:
        raise ValueError("pattern requires max_length to be set (ReDoS mitigation)")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise ValueError(f"pattern exceeds {MAX_PATTERN_LENGTH} chars (ReDoS mitigation)")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"invalid regex pattern: {exc}") from exc


def _validate_max_length(max_length: int | None) -> None:
    if max_length is None:
        return
    if max_length > RE_DOS_MAX_LENGTH:
        raise ValueError(f"max_length exceeds ReDoS mitigation limit ({RE_DOS_MAX_LENGTH})")
    if max_length > MAX_PARAM_LENGTH:
        raise ValueError(f"max_length exceeds system limit ({MAX_PARAM_LENGTH})")


def _verify_intent_references(
    intents: dict[str, IntentPolicy],
    output_filters: dict[str, OutputFilterDef],
) -> None:
    for intent_name, intent in intents.items():
        _verify_intent_output_filter(intent_name, intent, output_filters)
        _verify_guardrails_are_allowed_tools(intent_name, intent)


def _verify_intent_output_filter(
    intent_name: str,
    intent: IntentPolicy,
    output_filters: dict[str, OutputFilterDef],
) -> None:
    if intent.output_filter not in output_filters:
        raise ValueError(
            f"intent {intent_name!r} references unknown output_filter {intent.output_filter!r}"
        )


def _verify_guardrails_are_allowed_tools(intent_name: str, intent: IntentPolicy) -> None:
    allowed_tools = set(intent.allowed_tools)
    for tool_name in intent.guardrails:
        if tool_name not in allowed_tools:
            raise ValueError(f"intent {intent_name!r} guardrail {tool_name!r} not in allowed_tools")


def _verify_agent_intents(
    agents: dict[str, AgentPolicy],
    intents: dict[str, IntentPolicy],
) -> None:
    for agent_name, agent in agents.items():
        for intent_name in agent.allowed_intents:
            if intent_name not in intents:
                raise ValueError(f"agent {agent_name!r} references unknown intent {intent_name!r}")


def _verify_structural_allowlist_requires_schemas(
    output_filters: dict[str, OutputFilterDef],
) -> None:
    for filter_name, filter_def in output_filters.items():
        if filter_def.type == "structural_allowlist" and not filter_def.schemas:
            raise ValueError(
                f"output_filter {filter_name!r} type=structural_allowlist requires schemas"
            )


def _verify_structural_allowlist_schema_keys(
    output_filters: dict[str, OutputFilterDef],
    intents: dict[str, IntentPolicy],
) -> None:
    for filter_name, filter_def in output_filters.items():
        if filter_def.type != "structural_allowlist" or filter_def.schemas is None:
            continue
        _verify_schema_keys_are_referenced(filter_name, filter_def, intents)


def _verify_schema_keys_are_referenced(
    filter_name: str,
    filter_def: OutputFilterDef,
    intents: dict[str, IntentPolicy],
) -> None:
    referencing_tools = _referencing_tools_for_filter(filter_name, intents)
    for tool_name in filter_def.schemas or {}:
        if tool_name not in referencing_tools:
            raise ValueError(
                f"output_filter {filter_name!r} schema key {tool_name!r} is not "
                "referenced by any intent that uses this filter (typo?)"
            )


def _referencing_tools_for_filter(
    filter_name: str,
    intents: dict[str, IntentPolicy],
) -> set[str]:
    return {
        tool_name
        for intent in intents.values()
        if intent.output_filter == filter_name
        for tool_name in intent.allowed_tools
    }

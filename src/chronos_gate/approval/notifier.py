"""HITL approval notifier: abstract base + log-only stub implementation."""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Mapping, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)

_MASK = "**********"


def _deep_freeze(v: Any) -> Any:
    """再帰的にオブジェクトを不変な形式に変換します。"""
    if isinstance(v, (dict, MappingProxyType, Mapping)):
        return MappingProxyType({k: _deep_freeze(val) for k, val in v.items()})
    if isinstance(v, (list, tuple)):
        return tuple(_deep_freeze(i) for i in v)
    if isinstance(v, (set, frozenset)):
        return frozenset(_deep_freeze(i) for i in v)
    return v


class ApprovalRequest(BaseModel):
    """承認リクエストのデータモデル。"""

    model_config = ConfigDict(frozen=True)

    session_id: str
    approval_id: str
    agent_id: str
    intent: str
    tool_name: str
    arguments: Mapping[str, Any]
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("arguments", mode="after")
    @classmethod
    def _make_immutable(cls, v: Mapping[str, Any]) -> Mapping[str, Any]:
        """引数を再帰的に不変な形式に変換します。"""
        return cast(Mapping[str, Any], _deep_freeze(v))


def _sanitize_mapping(data: Any) -> dict[str, Any]:
    sensitive_tokens = {
        "api",
        "key",
        "token",
        "secret",
        "password",
        "authorization",
        "ssn",
        "email",
        "client",
    }
    new_data: dict[str, Any] = {}
    for k, v in data.items():
        key_str = str(k).lower()
        normalized_key = re.sub(r"[^a-z0-9]", "", key_str)
        is_sensitive = any(token in normalized_key for token in sensitive_tokens)
        if is_sensitive:
            new_data[str(k)] = _MASK
        else:
            new_data[str(k)] = sanitize_for_log(v)
    return new_data


def _sanitize_sequence(data: Any) -> Any:
    sanitized = [sanitize_for_log(i) for i in data]
    if isinstance(data, list):
        return sanitized
    if isinstance(data, tuple):
        return tuple(sanitized)
    return type(data)(sanitized)


def _is_sensitive_string(value: str) -> bool:
    if "@" in value and "." in value:
        return True
    if re.match(r"^\d{3}-\d{2}-\d{4}$", value):
        return True
    if re.search(r"Bearer\s+\S+", value, re.I):
        return True
    if re.match(r"^[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+$", value):
        return True
    if re.match(r"^[a-fA-F0-9]{32,}$", value):
        return True
    if len(value) >= 32 and re.match(r"^[a-zA-Z0-9+/]+={0,2}$", value):
        return True
    if re.match(r"^\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}$", value):
        return True
    return False


def sanitize_for_log(data: Any) -> Any:
    """ログ出力用に機密情報をマスクします。"""
    if isinstance(data, (dict, MappingProxyType, Mapping)):
        return _sanitize_mapping(data)
    if isinstance(data, (list, tuple, set, frozenset)):
        return _sanitize_sequence(data)
    if isinstance(data, str) and _is_sensitive_string(data):
        return _MASK
    return data


class ApprovalNotifier(ABC):
    """承認通知を行うための抽象基底クラス。"""

    @abstractmethod
    async def request_approval(self, request: ApprovalRequest) -> None:
        """承認をリクエストします。"""
        pass


class LogOnlyApprovalNotifier(ApprovalNotifier):
    """ログ出力のみを行う承認通知クラス。"""

    async def request_approval(self, request: ApprovalRequest) -> None:
        """ログに承認が必要な旨を出力します。"""
        # TODO: Slack Webhook / CIBA event queue への送信に差し替える
        logger.info(
            "approval_required sid=%s agent=%s intent=%s tool=%s args=%r requested_at=%s",
            request.session_id,
            request.agent_id,
            request.intent,
            request.tool_name,
            sanitize_for_log(request.arguments),
            request.requested_at.isoformat(),
        )

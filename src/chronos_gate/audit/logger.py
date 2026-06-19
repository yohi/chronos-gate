"""Audit logger.

stdout は MCP プロトコル通信に使うため絶対に汚染しない。
監査ログは stderr に JSON Lines で書き出す。
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from typing import Any, Literal

# シークレット判定用
_SENSITIVE_KEYS_FULL = {"api_key", "token", "secret", "authorization", "password"}
_SENSITIVE_KEYS_PREFIX = ("ck_",)

# 既知の非機密キー: 値の正規表現マスクをスキップする
_SAFE_KEYS = {"sid", "session_id"}

# 値に含まれるシークレットを検知する正規表現
# Bearer トークン、APIキー(sk-, ck-, ghp_等)、32文字以上の16進数(nonce/hash等)
_SENSITIVE_VALUE_RE = re.compile(
    r"(?i)(bearer\s+|sk-|ck-|ghp_|gho_|ghu_|ghs_|ghr_|AKIA|AIza)[a-zA-Z0-9._~+/-]+"
    r"|[0-9a-fA-F]{32,}",
)

_MASK = "**********"



class AuditLogger:
    def __init__(self, level: Literal["INFO", "DEBUG", "ERROR"] = "INFO") -> None:
        self.set_level(level)

    def set_level(self, level: Literal["INFO", "DEBUG", "ERROR"]) -> None:
        if level not in ("INFO", "DEBUG", "ERROR"):
            raise ValueError(f"Invalid log level: {level}. Expected 'INFO', 'DEBUG', or 'ERROR'.")
        self.level = level

    def log(
        self, *, ev: str, level: Literal["INFO", "DEBUG", "ERROR"] = "INFO", **fields: Any
    ) -> None:
        # 実行時レベルバリデーション
        if level not in ("INFO", "DEBUG", "ERROR"):
            raise ValueError(f"Invalid log level: {level}. Expected 'INFO', 'DEBUG', or 'ERROR'.")

        # ログレベルによるフィルタリング
        # ERROR は常に通す、INFO は INFO 以上を通す、DEBUG はすべて通す
        if self.level == "ERROR" and level != "ERROR":
            return
        if self.level == "INFO" and level == "DEBUG":
            return

        # 予約キーのチェック
        reserved = {"ts", "ev", "level"}
        conflicted = reserved & fields.keys()
        if conflicted:
            raise ValueError(f"reserved audit field(s): {', '.join(sorted(conflicted))}")

        # タイムスタンプ(マイクロ秒精度を強制)
        ts = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")

        record: dict[str, Any] = {
            "ts": ts,
            "ev": ev,
            "level": level,
        }

        # シークレットフィールドの再帰的フィルタリング
        record.update(self._sanitize_value(fields))
        sys.stderr.write(json.dumps(record, separators=(",", ":")) + "\n")
        sys.stderr.flush()

    def _sanitize_value(self, value: Any, key_name: str | None = None) -> Any:
        """再帰的に機密情報をマスクする。"""
        if self._should_mask_key(key_name):
            return _MASK
        if isinstance(value, str):
            return self._sanitize_string(value, key_name)
        if isinstance(value, dict):
            return self._sanitize_mapping(value)
        if isinstance(value, (list, tuple)):
            return self._sanitize_sequence(value, key_name)
        if self._is_json_primitive(value):
            return value
        return self._sanitize_object(value)

    def _should_mask_key(self, key_name: str | None) -> bool:
        if key_name is None:
            return False
        key_lower = key_name.lower()
        return key_lower in _SENSITIVE_KEYS_FULL or any(
            key_lower.startswith(prefix) for prefix in _SENSITIVE_KEYS_PREFIX
        )

    def _sanitize_string(self, value: str, key_name: str | None) -> str:
        if key_name is None:
            return _MASK if _SENSITIVE_VALUE_RE.search(value) else value

        key_lower = key_name.lower()
        if key_lower in {"stacktrace", "traceback"}:
            return _SENSITIVE_VALUE_RE.sub(_MASK, value)
        if key_lower in _SAFE_KEYS:
            return value
        return _MASK if _SENSITIVE_VALUE_RE.search(value) else value

    def _sanitize_mapping(self, value: dict[Any, Any]) -> dict[str, Any]:
        return {str(k): self._sanitize_value(v, key_name=str(k)) for k, v in value.items()}

    def _sanitize_sequence(
        self, value: list[Any] | tuple[Any, ...], key_name: str | None
    ) -> list[Any]:
        return [self._sanitize_value(item, key_name=key_name) for item in value]

    def _is_json_primitive(self, value: Any) -> bool:
        return isinstance(value, (int, float, bool)) or value is None

    def _sanitize_object(self, value: Any) -> str:
        text = str(value)
        if _SENSITIVE_VALUE_RE.search(text):
            return _MASK
        return text

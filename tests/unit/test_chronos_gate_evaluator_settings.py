from __future__ import annotations

import pytest
from pydantic import SecretStr

from chronos_gate.config import EvaluatorSettings


def test_defaults_match_design(monkeypatch: pytest.MonkeyPatch) -> None:
    """env が一切設定されていないときの既定値を検証する。"""
    for key in ["CHRONOS_EVALUATOR_API_KEY", "CHRONOS_EVALUATOR_MODEL"]:
        monkeypatch.delenv(key, raising=False)

    settings = EvaluatorSettings(_env_file=None)  # type: ignore[call-arg]

    assert settings.api_key is None
    assert settings.model == "anthropic/claude-haiku-4-5-20251001"


def test_env_vars_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHRONOS_EVALUATOR_API_KEY", "sk-test-123")
    monkeypatch.setenv("CHRONOS_EVALUATOR_MODEL", "openai/gpt-4o-mini")

    settings = EvaluatorSettings(_env_file=None)  # type: ignore[call-arg]

    assert isinstance(settings.api_key, SecretStr)
    assert settings.api_key.get_secret_value() == "sk-test-123"
    assert settings.model == "openai/gpt-4o-mini"


def test_api_key_is_secret_str(monkeypatch: pytest.MonkeyPatch) -> None:
    """SecretStr が repr, str, model_dump(mode='json') で値を漏らさないことを保証する。"""
    monkeypatch.setenv("CHRONOS_EVALUATOR_API_KEY", "should-not-leak")
    settings = EvaluatorSettings(_env_file=None)  # type: ignore[call-arg]

    assert "should-not-leak" not in repr(settings)
    assert "should-not-leak" not in str(settings)
    # model_dump(mode='json') でのマスクを確認
    dumped = settings.model_dump(mode="json")
    assert dumped["api_key"] == "**********"
    assert "should-not-leak" not in dumped["api_key"]


def test_extra_env_vars_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """数値系の CHRONOS_EVALUATOR_* env は本クラスでは読まず、ignore される。"""
    monkeypatch.setenv("CHRONOS_EVALUATOR_MAX_TOKENS", "9999")
    monkeypatch.setenv("CHRONOS_EVALUATOR_TIMEOUT_SECONDS", "99.9")

    settings = EvaluatorSettings(_env_file=None)  # type: ignore[call-arg]

    assert not hasattr(settings, "max_tokens")
    assert not hasattr(settings, 'timeout_seconds')

def test_api_account_id_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """CHRONOS_EVALUATOR_API_ACCOUNT_ID で api_account_id が設定されることを検証する。"""
    monkeypatch.setenv("CHRONOS_EVALUATOR_API_ACCOUNT_ID", "test-account-id")
    settings = EvaluatorSettings(_env_file=None)  # type: ignore[call-arg]
    assert settings.api_account_id is not None
    assert settings.api_account_id.get_secret_value() == "test-account-id"


def test_cloudflare_account_id_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLOUDFLARE_ACCOUNT_ID エイリアスで api_account_id が設定されることを検証。"""
    monkeypatch.setenv("CHRONOS_EVALUATOR_CLOUDFLARE_ACCOUNT_ID", "cf-account-id")
    settings = EvaluatorSettings(_env_file=None)  # type: ignore[call-arg]
    assert settings.api_account_id is not None
    assert settings.api_account_id.get_secret_value() == "cf-account-id"

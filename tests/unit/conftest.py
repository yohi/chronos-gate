import os

import pytest


@pytest.fixture(autouse=True)
def clean_gateway_env(monkeypatch):
    """Automatically clear all MCP_GATEWAY_* environment variables before each test."""
    for key in list(os.environ.keys()):
        if key.startswith("MCP_GATEWAY_"):
            monkeypatch.delenv(key, raising=False)

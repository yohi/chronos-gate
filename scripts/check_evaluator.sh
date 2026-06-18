#!/usr/bin/env bash
# Run all static analysis and tests for the Universal Evaluator inside the
# project's Devcontainer. Refuses to run on the host.
set -euo pipefail

# Devcontainer detection: explicit env vars only. Do NOT rely on /.dockerenv
# because that would pass for any container (e.g. `docker run python:3.12 ...`),
# silently running tests in an environment that may not have project deps.
if [ -z "${REMOTE_CONTAINERS:-}${CODESPACES:-}${DEVCONTAINER:-}" ]; then
    echo "ERROR: must run inside the project Devcontainer." >&2
    echo "       REMOTE_CONTAINERS / CODESPACES / DEVCONTAINER are all unset." >&2
    echo "" >&2
    echo "  How to fix:" >&2
    echo "    [VS Code]          choose 'Reopen in Container'" >&2
    echo "    [Codespaces]       CODESPACES=true is set automatically" >&2
    echo "    [devcontainer CLI] export DEVCONTAINER=1 (or rely on .devcontainer/setup.sh)" >&2
    exit 1
fi

TEST_FILES=(
    tests/unit/test_chronos_gate.py
    tests/unit/test_chronos_gate_cli.py
    tests/unit/test_chronos_gate_composite.py
    tests/unit/test_chronos_gate_evaluator_models.py
    tests/unit/test_chronos_gate_evaluator_settings.py
    tests/unit/test_chronos_gate_llm_evaluator.py
    tests/unit/test_chronos_gate_memory_client.py
    tests/integration/test_evaluator_cli_subprocess.py
)

echo "==> ruff check"
uv run ruff check src/chronos_gate "${TEST_FILES[@]}"

echo "==> ruff format --check"
uv run ruff format --check src/chronos_gate "${TEST_FILES[@]}"

echo "==> mypy"
uv run mypy src/chronos_gate

echo "==> pytest (unit)"
uv run pytest tests/unit/ -v

echo "==> pytest (integration, subprocess E2E)"
uv run pytest tests/integration/test_evaluator_cli_subprocess.py -v

echo "==> all checks passed"

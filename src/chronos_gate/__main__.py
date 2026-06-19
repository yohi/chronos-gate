from __future__ import annotations

import argparse
import os
import sys
import traceback


def _serve() -> None:
    """Default behaviour: run uvicorn HTTP server (legacy mode)."""
    import uvicorn

    from chronos_gate.audit.logger import AuditLogger

    try:
        host = os.getenv("MCP_GATEWAY_HOST", "127.0.0.1")
        port_str = os.getenv("MCP_GATEWAY_PORT", "9100")
        try:
            port = int(port_str)
        except ValueError as e:
            raise ValueError(f"MCP_GATEWAY_PORT must be an integer, got: {port_str!r}") from e
        uvicorn.run(
            "chronos_gate.app:build_app",
            factory=True,
            host=host,
            port=port,
            log_level="info",
        )
    except Exception as e:
        AuditLogger().log(
            ev="startup_failure",
            level="ERROR",
            error=str(e),
            error_type=type(e).__name__,
            stacktrace=traceback.format_exc(),
        )
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(prog="chronos-gate")
    _ = parser.add_argument(
        "command",
        nargs="?",
        choices=("evaluate", "run"),
        default="run",
        help="subcommand to run: evaluate JSON tool calls or run the HTTP server",
    )
    args, remaining = parser.parse_known_args(sys.argv[1:])

    if args.command == "evaluate":
        from chronos_gate.cli import main as cli_main

        sys.exit(cli_main(remaining))
    if remaining:
        parser.error(f"unrecognized arguments: {' '.join(remaining)}")
    _serve()


if __name__ == "__main__":
    main()

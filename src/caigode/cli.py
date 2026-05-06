"""Command line entrypoint for the caigode CLI."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .config import ConfigError, load_config
from .interface.run_handler import handle_run
from .interface.status_handler import handle_status


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level argument parser and register subcommands."""

    parser = argparse.ArgumentParser(prog="caigode")
    subparsers = parser.add_subparsers(dest="command")

    for command_name in ("chat", "review"):
        subparser = subparsers.add_parser(command_name, help=_command_help(command_name))
        _add_config_arguments(subparser)
        subparser.set_defaults(handler=_build_placeholder_handler(command_name))

    run_parser = subparsers.add_parser("run", help=_command_help("run"))
    _add_config_arguments(run_parser)
    run_parser.add_argument("prompt", help="Task prompt to execute.")
    run_parser.add_argument(
        "--context-file",
        action="append",
        default=[],
        help="Workspace-relative file to read before planning. Repeatable.",
    )
    run_parser.add_argument(
        "--verify",
        action="append",
        default=[],
        help="Verification command to run after file writes. Repeatable.",
    )
    run_parser.set_defaults(handler=handle_run)

    status_parser = subparsers.add_parser("status", help=_command_help("status"))
    _add_workspace_arguments(status_parser)
    status_parser.set_defaults(handler=handle_status)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and translate configuration failures into exit codes."""

    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0

    try:
        return handler(args)
    except ConfigError as exc:
        parser.exit(status=2, message=f"{exc}\n")


def _add_config_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", help="OpenAI-compatible model name.")
    parser.add_argument("--base-url", help="OpenAI-compatible API base URL.")
    parser.add_argument("--api-key", help="API key used for model requests.")
    _add_workspace_arguments(parser)


def _add_workspace_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        help="Workspace root directory for file and command operations.",
    )
    parser.add_argument(
        "--state-dir",
        help="Directory used to persist session state and artifacts.",
    )


def _build_placeholder_handler(command_name: str):
    def handler(args: argparse.Namespace) -> int:
        config = load_config(
            model=args.model,
            base_url=args.base_url,
            api_key=args.api_key,
            workspace=args.workspace,
            state_dir=args.state_dir,
        )
        print(
            f"{command_name} command is not implemented yet. "
            f"Workspace: {config.workspace}"
        )
        return 0

    return handler


def _command_help(command_name: str) -> str:
    return {
        "chat": "Start an interactive coding session.",
        "run": "Execute a non-interactive coding task.",
        "status": "Show the latest session status.",
        "review": "Generate a local delivery review artifact.",
    }[command_name]


if __name__ == "__main__":
    sys.exit(main())

"""Loguetown CLI entry point — ``lt <command> [args]``.

Commands
--------
lt init       Scaffold .loguetown/ in the current repo
lt prime      Print session context for injection via the SessionStart hook
lt role       Manage role YAML files
lt agent      Manage agent Charter YAML files
lt skills     Manage skill module directories
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="lt",
        description="Loguetown — local-first multi-agent coding assistant",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True

    # Register each command module
    from core.commands import agent_cmd, init_cmd, role_cmd, skills_cmd

    init_cmd.add_parser(subparsers)
    role_cmd.add_parser(subparsers)
    agent_cmd.add_parser(subparsers)
    skills_cmd.add_parser(subparsers)
    _add_prime_parser(subparsers)

    args = parser.parse_args()
    args.func(args)


def _add_prime_parser(subparsers) -> None:  # type: ignore[type-arg]
    """Register 'lt prime' — forwards to core.prime."""
    p = subparsers.add_parser(
        "prime",
        help="Print session context for injection via the SessionStart hook",
    )
    p.add_argument(
        "--hook",
        action="store_true",
        help="Hook mode: read SessionStart JSON from stdin",
    )
    p.add_argument(
        "--workdir",
        type=__import__("pathlib").Path,
        default=None,
        help="Working directory (default: current directory)",
    )
    p.set_defaults(func=_prime_handler)


def _prime_handler(args) -> None:  # type: ignore[type-arg]
    import json
    from pathlib import Path

    from core.prime import build_prime_output

    workdir = (args.workdir or Path.cwd()).resolve()
    hook_input: dict | None = None
    if args.hook:
        raw = sys.stdin.read().strip()
        if raw:
            try:
                hook_input = json.loads(raw)
            except json.JSONDecodeError:
                pass
    print(build_prime_output(workdir=workdir, hook_input=hook_input))

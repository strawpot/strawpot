#!/usr/bin/env python3
"""Stub agent wrapper for E2E tests.

Implements the strawpot agent wrapper protocol:
  stub_wrapper.py setup  -> exit 0
  stub_wrapper.py build <protocol-args> -> JSON {"cmd": [...], "cwd": "..."}

The "build" subcommand returns a command that runs stub_agent.py
(or the script specified by STUB_AGENT_SCRIPT env var),
passing through --task, --working-dir, and --agent-workspace-dir.
"""

import argparse
import json
import os
import sys


def main():
    if len(sys.argv) < 2:
        sys.exit(1)

    subcommand = sys.argv[1]

    if subcommand == "setup":
        sys.exit(0)

    if subcommand == "build":
        parser = argparse.ArgumentParser()
        parser.add_argument("--agent-id", default="")
        parser.add_argument("--working-dir", default="")
        parser.add_argument("--agent-workspace-dir", default="")
        parser.add_argument("--role-prompt", default="")
        parser.add_argument("--memory-prompt", default="")
        parser.add_argument("--task", default="")
        parser.add_argument("--config", default="{}")
        parser.add_argument("--skills-dir", default="")
        parser.add_argument("--roles-dir", action="append", default=[])
        args = parser.parse_args(sys.argv[2:])

        agent_script = os.environ.get(
            "STUB_AGENT_SCRIPT",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "stub_agent.py"),
        )

        cmd = [
            sys.executable,
            agent_script,
            "--task", args.task,
            "--working-dir", args.working_dir,
            "--agent-workspace-dir", args.agent_workspace_dir,
        ]

        result = {"cmd": cmd, "cwd": args.working_dir or os.getcwd()}
        json.dump(result, sys.stdout)
        sys.exit(0)

    sys.exit(1)


if __name__ == "__main__":
    main()

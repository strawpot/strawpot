#!/usr/bin/env python3
"""Stub agent process for E2E tests.

Writes deterministic output based on the --task string:
  "write <filename>"       -> creates <filename> in working-dir
  "exit <code>"            -> exits with the given code
  "sleep <seconds>"        -> sleeps then exits
  "output-json <json>"     -> prints the JSON string
  (anything else)          -> prints "Agent completed task" and exits 0
"""

import argparse
import os
import subprocess
import sys
import time


def _git_commit(filepath, working_dir):
    """Stage and commit a file if running in a git repo."""
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=working_dir,
        capture_output=True,
    )
    if result.returncode != 0:
        return  # not a git repo
    subprocess.run(
        ["git", "add", filepath],
        cwd=working_dir,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", f"Add {os.path.basename(filepath)}"],
        cwd=working_dir,
        capture_output=True,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default="")
    parser.add_argument("--working-dir", default="")
    parser.add_argument("--agent-workspace-dir", default="")
    args = parser.parse_args()

    task = args.task.strip()

    if task.startswith("write "):
        filename = task.split(" ", 1)[1]
        filepath = os.path.join(args.working_dir, filename)
        os.makedirs(os.path.dirname(filepath), exist_ok=True) if os.path.dirname(filepath) else None
        with open(filepath, "w") as f:
            f.write("Written by stub agent\n")
        _git_commit(filepath, args.working_dir)
        print(f"Created {filename}")

    elif task.startswith("exit "):
        code = int(task.split(" ", 1)[1])
        print(f"Exiting with code {code}")
        sys.exit(code)

    elif task.startswith("sleep "):
        duration = float(task.split(" ", 1)[1])
        time.sleep(duration)
        print("Slept and done")

    elif task.startswith("output-json "):
        json_str = task.split(" ", 1)[1]
        print(json_str)

    else:
        print("Agent completed task")


if __name__ == "__main__":
    main()

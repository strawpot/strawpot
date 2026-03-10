#!/usr/bin/env python3
"""Stub agent that sends a delegation request via denden gRPC.

Reads DENDEN_ADDR, DENDEN_AGENT_ID, and DENDEN_RUN_ID from env.
Parses the task string for delegation instructions:
  "delegate <role_slug> <task_text>"  -> sends delegation request
  (anything else)                     -> prints and exits

Uses the Python gRPC client from denden.gen.
"""

import argparse
import os
import sys

import grpc

from denden.gen import denden_pb2, denden_pb2_grpc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default="")
    parser.add_argument("--working-dir", default="")
    parser.add_argument("--agent-workspace-dir", default="")
    args = parser.parse_args()

    task = args.task.strip()
    parts = task.split(" ", 2)

    if len(parts) < 3 or parts[0] != "delegate":
        # Fall back to stub_agent behavior for non-delegation tasks
        if task.startswith("write "):
            filename = task.split(" ", 1)[1]
            filepath = os.path.join(args.working_dir, filename)
            with open(filepath, "w") as f:
                f.write("Written by stub agent\n")
            print(f"Created {filename}")
        elif task.startswith("exit "):
            code = int(task.split(" ", 1)[1])
            sys.exit(code)
        elif task.startswith("sleep "):
            import time
            time.sleep(float(task.split(" ", 1)[1]))
            print("Slept and done")
        else:
            print("Agent completed (no delegation)")
        return

    role_slug = parts[1]
    task_text = parts[2]

    addr = os.environ.get("DENDEN_ADDR", "127.0.0.1:9700")
    agent_id = os.environ.get("DENDEN_AGENT_ID", "stub")
    run_id = os.environ.get("DENDEN_RUN_ID", "run_stub")

    channel = grpc.insecure_channel(addr)
    stub = denden_pb2_grpc.DendenStub(channel)

    request = denden_pb2.DenDenRequest(
        denden_version="1.0",
        request_id=f"req_{agent_id}",
        trace=denden_pb2.Trace(
            run_id=run_id,
            agent_instance_id=agent_id,
        ),
        delegate=denden_pb2.DelegatePayload(
            delegate_to=role_slug,
            task=denden_pb2.Task(text=task_text),
        ),
    )

    response = stub.Send(request)

    if response.status == denden_pb2.OK:
        print("Delegation result: OK")
    elif response.status == denden_pb2.DENIED:
        print(f"Delegation denied: {response.error.code}")
    else:
        print(f"Delegation error: {response.error.message}")


if __name__ == "__main__":
    main()

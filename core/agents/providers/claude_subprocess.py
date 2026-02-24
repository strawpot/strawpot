from __future__ import annotations

import asyncio
import json
import shutil
from typing import AsyncIterator

from ..types import AgentResponse, Message


class ClaudeSubprocessProvider:
    """Provider that shells out to the `claude` CLI (non-interactive mode).

    Uses ``claude --print --output-format json`` for complete responses and
    ``claude --print --output-format stream-json`` for streaming.

    The full conversation (system prompt + history) is serialised as a plain
    text prompt and piped to stdin so the subprocess sees the whole context.
    """

    def __init__(
        self,
        claude_path: str | None = None,
        default_model: str | None = None,
    ) -> None:
        self._claude_path = claude_path or shutil.which("claude") or "claude"
        self._default_model = default_model

    @property
    def name(self) -> str:
        return "claude_subprocess"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_cmd(self, model: str | None, output_format: str) -> list[str]:
        cmd = [self._claude_path, "--print", "--output-format", output_format]
        resolved_model = model or self._default_model
        if resolved_model:
            cmd.extend(["--model", resolved_model])
        return cmd

    def _serialize_prompt(self, messages: list[Message], system: str | None) -> bytes:
        """Flatten conversation into plain text for stdin."""
        parts: list[str] = []
        if system:
            parts.append(f"<system>\n{system}\n</system>")
        for msg in messages:
            tag = msg["role"].upper()
            parts.append(f"<{tag}>\n{msg['content']}\n</{tag}>")
        return ("\n\n".join(parts)).encode()

    # ------------------------------------------------------------------
    # Provider interface
    # ------------------------------------------------------------------

    async def complete(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 8096,
        **kwargs,
    ) -> AgentResponse:
        cmd = self._build_cmd(model, "json")
        prompt = self._serialize_prompt(messages, system)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=prompt)

        if proc.returncode != 0:
            raise RuntimeError(
                f"claude subprocess exited with code {proc.returncode}: "
                f"{stderr.decode().strip()}"
            )

        raw = stdout.decode().strip()
        try:
            data = json.loads(raw)
            # Claude CLI JSON output: {"type":"result","result":"...","cost_usd":...}
            content = data.get("result") or data.get("content") or raw
        except json.JSONDecodeError:
            content = raw

        return AgentResponse(
            content=content,
            model=model or self._default_model,
        )

    async def stream(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 8096,
        **kwargs,
    ) -> AsyncIterator[str]:
        cmd = self._build_cmd(model, "stream-json")
        prompt = self._serialize_prompt(messages, system)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Write prompt and close stdin so the subprocess can start
        proc.stdin.write(prompt)
        await proc.stdin.drain()
        proc.stdin.close()

        async for raw_line in proc.stdout:
            line = raw_line.decode().strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Stream-JSON format: {"type":"content_block_delta","delta":{"type":"text_delta","text":"..."}}
            if event.get("type") == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    if text:
                        yield text

        await proc.wait()
        if proc.returncode not in (0, None):
            stderr_out = await proc.stderr.read()
            raise RuntimeError(
                f"claude subprocess exited with code {proc.returncode}: "
                f"{stderr_out.decode().strip()}"
            )

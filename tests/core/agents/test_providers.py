"""Tests for concrete providers.

ClaudeAPIProvider: mocks the anthropic client.
ClaudeSubprocessProvider: mocks asyncio.create_subprocess_exec.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agents.providers.claude_api import ClaudeAPIProvider
from core.agents.providers.claude_subprocess import ClaudeSubprocessProvider
from core.agents.types import Message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def user(content: str) -> Message:
    return {"role": "user", "content": content}


def assistant(content: str) -> Message:
    return {"role": "assistant", "content": content}


# ---------------------------------------------------------------------------
# ClaudeAPIProvider
# ---------------------------------------------------------------------------


class TestClaudeAPIProvider:
    @pytest.fixture
    def mock_client(self):
        with patch("core.agents.providers.claude_api.anthropic.AsyncAnthropic") as cls:
            instance = cls.return_value
            yield instance

    @pytest.fixture
    def provider(self, mock_client):
        return ClaudeAPIProvider(api_key="test-key")

    def test_name(self, provider):
        assert provider.name == "claude_api"

    async def test_complete_returns_response(self, provider, mock_client):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="hello from claude")]
        mock_response.model = "claude-sonnet-4-6"
        mock_response.stop_reason = "end_turn"
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        response = await provider.complete([user("hi")], system="be helpful")

        assert response.content == "hello from claude"
        assert response.model == "claude-sonnet-4-6"
        assert response.stop_reason == "end_turn"
        assert response.usage == {"input_tokens": 10, "output_tokens": 5}

    async def test_complete_passes_system(self, provider, mock_client):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="ok")]
        mock_response.model = "m"
        mock_response.stop_reason = "end_turn"
        mock_response.usage.input_tokens = 1
        mock_response.usage.output_tokens = 1
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        await provider.complete([user("hi")], system="you are an expert")

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "you are an expert"

    async def test_complete_no_system_skips_key(self, provider, mock_client):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="ok")]
        mock_response.model = "m"
        mock_response.stop_reason = "end_turn"
        mock_response.usage.input_tokens = 1
        mock_response.usage.output_tokens = 1
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        await provider.complete([user("hi")])

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "system" not in call_kwargs

    async def test_stream_yields_chunks(self, provider, mock_client):
        async def fake_text_stream():
            for chunk in ["Hello", " world"]:
                yield chunk

        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_ctx)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_stream_ctx.text_stream = fake_text_stream()
        mock_client.messages.stream = MagicMock(return_value=mock_stream_ctx)

        chunks = []
        async for chunk in provider.stream([user("hi")]):
            chunks.append(chunk)

        assert chunks == ["Hello", " world"]

    async def test_uses_default_model(self, provider, mock_client):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="ok")]
        mock_response.model = "claude-sonnet-4-6"
        mock_response.stop_reason = "end_turn"
        mock_response.usage.input_tokens = 1
        mock_response.usage.output_tokens = 1
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        await provider.complete([user("hi")])

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-opus-4-6"

    async def test_model_override(self, provider, mock_client):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="ok")]
        mock_response.model = "claude-opus-4-6"
        mock_response.stop_reason = "end_turn"
        mock_response.usage.input_tokens = 1
        mock_response.usage.output_tokens = 1
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        await provider.complete([user("hi")], model="claude-opus-4-6")

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-opus-4-6"


# ---------------------------------------------------------------------------
# ClaudeSubprocessProvider
# ---------------------------------------------------------------------------


def _make_proc(stdout_data: bytes, returncode: int = 0, stderr_data: bytes = b""):
    """Build a mock asyncio Process."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout_data, stderr_data))
    proc.wait = AsyncMock()

    # Writable stdin
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()
    proc.stdin.close = MagicMock()

    # Readable stdout (async line iterator)
    proc.stderr = MagicMock()
    proc.stderr.read = AsyncMock(return_value=stderr_data)

    return proc


class TestClaudeSubprocessProvider:
    @pytest.fixture
    def provider(self):
        return ClaudeSubprocessProvider(claude_path="claude", default_model=None)

    def test_name(self, provider):
        assert provider.name == "claude_subprocess"

    async def test_complete_json_result(self, provider):
        output = json.dumps({"type": "result", "result": "hello from subprocess"}).encode()
        proc = _make_proc(output)

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            response = await provider.complete([user("hi")])

        assert response.content == "hello from subprocess"

    async def test_complete_fallback_to_raw(self, provider):
        proc = _make_proc(b"plain text output")

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            response = await provider.complete([user("hi")])

        assert response.content == "plain text output"

    async def test_complete_nonzero_exit_raises(self, provider):
        proc = _make_proc(b"", returncode=1, stderr_data=b"error!")

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            with pytest.raises(RuntimeError, match="exited with code 1"):
                await provider.complete([user("hi")])

    async def test_complete_includes_system_in_prompt(self, provider):
        output = json.dumps({"result": "ok"}).encode()
        proc = _make_proc(output)

        captured_input = []

        async def fake_exec(*args, **kwargs):
            return proc

        original_communicate = proc.communicate

        async def capturing_communicate(input=None):
            captured_input.append(input)
            return await original_communicate(input=input)

        proc.communicate = capturing_communicate

        with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=fake_exec)):
            await provider.complete([user("hello")], system="be concise")

        assert b"<system>" in captured_input[0]
        assert b"be concise" in captured_input[0]

    async def test_stream_yields_text_deltas(self, provider):
        events = [
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello"}},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": " world"}},
            {"type": "message_stop"},
        ]
        lines = [json.dumps(e).encode() + b"\n" for e in events]

        proc = MagicMock()
        proc.returncode = 0
        proc.stdin = MagicMock()
        proc.stdin.write = MagicMock()
        proc.stdin.drain = AsyncMock()
        proc.stdin.close = MagicMock()
        proc.stderr = MagicMock()
        proc.stderr.read = AsyncMock(return_value=b"")
        proc.wait = AsyncMock()

        async def fake_stdout():
            for line in lines:
                yield line

        proc.stdout = fake_stdout()

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            chunks = []
            async for chunk in provider.stream([user("hi")]):
                chunks.append(chunk)

        assert chunks == ["Hello", " world"]

    def test_serialize_prompt_with_system(self, provider):
        messages: list[Message] = [user("hello"), assistant("hi"), user("again")]
        result = provider._serialize_prompt(messages, "be helpful").decode()
        assert "<system>" in result
        assert "be helpful" in result
        assert "<USER>" in result
        assert "<ASSISTANT>" in result

    def test_serialize_prompt_no_system(self, provider):
        messages: list[Message] = [user("hello")]
        result = provider._serialize_prompt(messages, None).decode()
        assert "<system>" not in result
        assert "<USER>" in result

    def test_build_cmd_with_model(self, provider):
        cmd = provider._build_cmd("claude-opus-4-6", "json")
        assert "--model" in cmd
        assert "claude-opus-4-6" in cmd

    def test_build_cmd_no_model(self, provider):
        cmd = provider._build_cmd(None, "json")
        assert "--model" not in cmd

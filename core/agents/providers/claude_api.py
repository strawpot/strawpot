from __future__ import annotations

from typing import AsyncIterator

import anthropic

from ..types import AgentResponse, Message

DEFAULT_MODEL = "claude-opus-4-6"


class ClaudeAPIProvider:
    """Provider backed by the Anthropic Messages API (async)."""

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = DEFAULT_MODEL,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._default_model = default_model

    @property
    def name(self) -> str:
        return "claude_api"

    async def complete(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 8096,
        **kwargs,
    ) -> AgentResponse:
        extra: dict = {}
        if system:
            extra["system"] = system

        response = await self._client.messages.create(
            model=model or self._default_model,
            max_tokens=max_tokens,
            messages=messages,  # type: ignore[arg-type]
            **extra,
            **kwargs,
        )
        return AgentResponse(
            content=response.content[0].text,
            model=response.model,
            stop_reason=response.stop_reason,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
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
        extra: dict = {}
        if system:
            extra["system"] = system

        async with self._client.messages.stream(
            model=model or self._default_model,
            max_tokens=max_tokens,
            messages=messages,  # type: ignore[arg-type]
            **extra,
            **kwargs,
        ) as stream:
            async for text in stream.text_stream:
                yield text

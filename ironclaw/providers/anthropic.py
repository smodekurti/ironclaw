"""
ironclaw.providers.anthropic
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Anthropic Claude provider.

Translates IronClaw's OpenAI-compatible message format to Anthropic's
Messages API wire format and back.

Requires: ``pip install anthropic``
"""

from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

from ironclaw.core.message import ToolCall
from ironclaw.providers.base import LLMProvider, LLMResponse

try:
    import anthropic as _anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False


_DEFAULT_MODEL = "claude-sonnet-4-6"


class AnthropicProvider(LLMProvider):
    """
    Claude provider via the official ``anthropic`` Python SDK.

    Parameters
    ----------
    api_key : str | None
        Anthropic API key.  Falls back to ``ANTHROPIC_API_KEY`` env var.
    model : str
        Model string, e.g. ``"claude-opus-4-6"`` or ``"claude-haiku-4-5-20251001"``.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = _DEFAULT_MODEL,
    ) -> None:
        if not _ANTHROPIC_AVAILABLE:
            raise ImportError(
                "The 'anthropic' package is required: pip install anthropic"
            )
        self.model = model
        self._client = _anthropic.AsyncAnthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _split_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        """Convert OpenAI-format messages to Anthropic system + chat lists."""
        system_text = ""
        chat_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg["role"] == "system":
                system_text += msg["content"] + "\n"
            elif msg["role"] == "tool":
                chat_messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg["tool_call_id"],
                            "content": msg["content"],
                        }
                    ],
                })
            elif msg["role"] == "assistant" and "tool_calls" in msg:
                content_blocks: list[dict] = []
                if msg.get("content"):
                    content_blocks.append({"type": "text", "text": msg["content"]})
                for tc in msg.get("tool_calls", []):
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["function"]["name"],
                        "input": tc["function"]["arguments"],
                    })
                chat_messages.append({"role": "assistant", "content": content_blocks})
            else:
                chat_messages.append({"role": msg["role"], "content": msg["content"]})

        return system_text, chat_messages

    @staticmethod
    def _build_tool_schemas(tools: list[dict[str, Any]] | None) -> list[dict]:
        anthropic_tools = []
        for t in (tools or []):
            fn = t.get("function", t)
            anthropic_tools.append({
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        return anthropic_tools

    # ------------------------------------------------------------------
    # complete() — blocking, returns full LLMResponse
    # ------------------------------------------------------------------

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        system_text, chat_messages = self._split_messages(messages)
        anthropic_tools = self._build_tool_schemas(tools)

        call_kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=chat_messages,
            system=system_text.strip() or None,
            **kwargs,
        )
        if anthropic_tools:
            call_kwargs["tools"] = anthropic_tools

        resp = await self._client.messages.create(**call_kwargs)

        # Parse response
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                args = block.input if isinstance(block.input, dict) else json.loads(block.input)
                tool_calls.append(ToolCall(
                    tool_name=block.name,
                    arguments=args,
                    call_id=block.id,
                ))

        return LLMResponse(
            content=" ".join(text_parts),
            tool_calls=tool_calls,
            model=resp.model,
            usage={
                "prompt_tokens": resp.usage.input_tokens,
                "completion_tokens": resp.usage.output_tokens,
            },
            raw=resp,
        )

    # ------------------------------------------------------------------
    # stream() — real token-by-token streaming via the Anthropic SDK
    # Tool-call turns must use complete(); only call stream() for the
    # final text-only response so the SSE endpoint delivers true chunks.
    # ------------------------------------------------------------------

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        system_text, chat_messages = self._split_messages(messages)

        call_kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=chat_messages,
            system=system_text.strip() or None,
            **kwargs,
        )
        # Never pass tools to the streaming call — streaming is text-only.
        # Tool-call rounds always go through complete().

        async with self._client.messages.stream(**call_kwargs) as s:
            async for text in s.text_stream:
                yield text

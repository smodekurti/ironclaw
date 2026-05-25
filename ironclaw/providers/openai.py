"""
ironclaw.providers.openai
~~~~~~~~~~~~~~~~~~~~~~~~~
OpenAI (and OpenAI-compatible) provider.

Requires: ``pip install openai``
"""

from __future__ import annotations

import json
import os
from typing import Any

from ironclaw.core.message import ToolCall
from ironclaw.providers.base import LLMProvider, LLMResponse

try:
    from openai import AsyncOpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False

_DEFAULT_MODEL = "gpt-4o"


class OpenAIProvider(LLMProvider):
    """
    OpenAI ChatCompletion provider.

    Also works with any OpenAI-compatible endpoint (Together AI, Groq,
    vLLM, etc.) by setting ``base_url``.

    Parameters
    ----------
    api_key : str | None
        Falls back to ``OPENAI_API_KEY`` env var.
    model : str
        Model name.
    base_url : str | None
        Override base URL for OpenAI-compatible APIs.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = _DEFAULT_MODEL,
        base_url: str | None = None,
    ) -> None:
        if not _OPENAI_AVAILABLE:
            raise ImportError("The 'openai' package is required: pip install openai")
        self.model = model
        self._client = AsyncOpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY", ""),
            base_url=base_url,
        )

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        call_kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )
        if tools:
            call_kwargs["tools"] = tools
            call_kwargs["tool_choice"] = "auto"

        resp = await self._client.chat.completions.create(**call_kwargs)
        choice = resp.choices[0]
        msg = choice.message

        text_content = msg.content or ""
        tool_calls: list[ToolCall] = []

        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            tool_calls.append(ToolCall(
                tool_name=tc.function.name,
                arguments=args,
                call_id=tc.id,
            ))

        return LLMResponse(
            content=text_content,
            tool_calls=tool_calls,
            model=resp.model,
            usage={
                "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
            },
            raw=resp,
        )

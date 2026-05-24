"""
ironclaw.providers.cohere
~~~~~~~~~~~~~~~~~~~~~~~~~~
Cohere provider via the `cohere` SDK.

Install:  pip install cohere

Supported models:
  command-r-plus    — flagship (128k context)
  command-r         — balanced
  command-light     — fast and affordable
"""

from __future__ import annotations

import os
from typing import Any

from ironclaw.core.message import Message, Role, ToolCall
from ironclaw.exceptions import ProviderError
from ironclaw.providers.base import LLMProvider, LLMResponse

_DEFAULT_MODEL = "command-r-plus"


class CohereProvider(LLMProvider):
    """
    Cohere Chat provider.

    Parameters
    ----------
    api_key : str | None
        Defaults to ``COHERE_API_KEY`` env var.
    model : str
        Cohere model (default: command-r-plus).
    temperature : float
    max_tokens : int
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = _DEFAULT_MODEL,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> None:
        self.api_key = api_key or os.environ.get("COHERE_API_KEY", "")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def complete(
        self,
        messages: list[Message],
        tool_schemas: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        try:
            import cohere
        except ImportError as e:
            raise ProviderError("cohere not installed. Run: pip install cohere") from e

        if not self.api_key:
            raise ProviderError("COHERE_API_KEY not set")

        client = cohere.AsyncClientV2(api_key=self.api_key)

        # Separate system prompt
        system_msg = next((m.content for m in messages if m.role == Role.SYSTEM), None)

        chat_history = []
        for m in messages:
            if m.role == Role.SYSTEM:
                continue
            if m.role == Role.USER:
                chat_history.append({"role": "user", "content": m.content or ""})
            elif m.role == Role.ASSISTANT:
                chat_history.append({"role": "assistant", "content": m.content or ""})
            elif m.role == Role.TOOL_RESULT and m.tool_results:
                for tr in m.tool_results:
                    chat_history.append({
                        "role": "tool",
                        "tool_call_id": tr.call_id,
                        "content": str(tr.output),
                    })

        # Build Cohere tool definitions
        cohere_tools = []
        if tool_schemas:
            for schema in tool_schemas:
                fn = schema.get("function", schema)
                params = fn.get("parameters", {})
                cohere_tools.append(cohere.ToolV2(
                    type="function",
                    function=cohere.ToolV2Function(
                        name=fn["name"],
                        description=fn.get("description", ""),
                        parameters=params,
                    ),
                ))

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": chat_history,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if system_msg:
            kwargs["messages"] = [{"role": "system", "content": system_msg}] + chat_history
        if cohere_tools:
            kwargs["tools"] = cohere_tools

        try:
            resp = await client.chat(**kwargs)
        except Exception as e:
            raise ProviderError(f"Cohere API error: {e}") from e

        content = ""
        tool_calls: list[ToolCall] = []
        import json

        for block in resp.message.content or []:
            if hasattr(block, "text"):
                content += block.text
            elif hasattr(block, "type") and block.type == "tool_use":
                try:
                    args = json.loads(block.input) if isinstance(block.input, str) else block.input
                except Exception:
                    args = {}
                tool_calls.append(ToolCall(
                    tool_name=block.name,
                    arguments=args,
                    call_id=block.id,
                ))

        return LLMResponse(content=content, tool_calls=tool_calls)

    @property
    def provider_name(self) -> str:
        return "cohere"

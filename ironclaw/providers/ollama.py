"""
ironclaw.providers.ollama
~~~~~~~~~~~~~~~~~~~~~~~~~
Local Ollama provider (OpenAI-compatible endpoint).

Ollama exposes a local OpenAI-compatible API at http://localhost:11434.
This provider is a thin wrapper around the OpenAI provider pointed at
the local endpoint — no extra dependencies needed beyond ``openai``.

Requires: ``pip install openai`` + a running Ollama daemon.
"""

from __future__ import annotations

from typing import Any

from ironclaw.providers.base import LLMProvider, LLMResponse
from ironclaw.providers.openai import OpenAIProvider

_DEFAULT_BASE_URL = "http://localhost:11434/v1"
_DEFAULT_MODEL = "llama3"


class OllamaProvider(LLMProvider):
    """
    Local Ollama provider.

    Parameters
    ----------
    model : str
        Ollama model name, e.g. ``"llama3"``, ``"mistral"``, ``"phi3"``.
    base_url : str
        Ollama server URL (default: http://localhost:11434/v1).
    """

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        base_url: str = _DEFAULT_BASE_URL,
    ) -> None:
        self.model = model
        self._inner = OpenAIProvider(
            api_key="ollama",  # Ollama doesn't validate the key
            model=model,
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
        return await self._inner.complete(
            messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

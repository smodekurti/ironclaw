"""
ironclaw.providers.base
~~~~~~~~~~~~~~~~~~~~~~~
Abstract LLM provider interface.

All concrete providers (Anthropic, OpenAI, Ollama…) implement this interface
so that agents are fully decoupled from the underlying model API.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from ironclaw.core.message import ToolCall


@dataclass
class LLMResponse:
    """Normalised response from any LLM provider."""
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)  # prompt/completion tokens
    raw: Any = None   # provider-specific raw response, for debugging


class LLMProvider(ABC):
    """
    Abstract base for all LLM providers.

    Implementors must override ``complete``.  Providers should be stateless
    (no conversation history stored here — that lives in ConversationMemory).

    Streaming
    ---------
    ``stream()`` is optional — the default implementation falls back to
    ``complete()`` and yields the full text as one chunk.  Override it in
    concrete providers to get true token-by-token streaming.
    """

    model: str = ""

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Send *messages* to the LLM and return a normalised response.

        Parameters
        ----------
        messages : list[dict]
            OpenAI-compatible message list (role + content).
        tools : list[dict] | None
            OpenAI-compatible tool schemas.  Pass ``[]`` or ``None`` to
            disable tool calling.
        max_tokens : int
            Upper bound on generated tokens.
        temperature : float
            Sampling temperature.
        """
        ...

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """
        Stream text tokens from the LLM as they are generated.

        This default implementation calls ``complete()`` and yields the
        full content as a single chunk.  Override in concrete providers to
        get real token-by-token streaming.

        Yields
        ------
        str
            Individual text tokens / chunks as they arrive from the model.
            Tool-call turns are NOT streamed — ``complete()`` is used for
            those so that all tool-call metadata is captured atomically.
        """
        response = await self.complete(messages, tools=tools,
                                       max_tokens=max_tokens,
                                       temperature=temperature, **kwargs)
        if response.content:
            yield response.content

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} model={self.model!r}>"

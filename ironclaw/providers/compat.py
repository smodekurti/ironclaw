"""
ironclaw.providers.compat
~~~~~~~~~~~~~~~~~~~~~~~~~~
OpenAI-compatible provider — covers any service that implements the
OpenAI Chat Completions API.

This single class backs:
  - Groq                 (https://api.groq.com/openai/v1)
  - Mistral AI           (https://api.mistral.ai/v1)
  - Together AI          (https://api.together.xyz/v1)
  - Perplexity           (https://api.perplexity.ai)
  - xAI / Grok           (https://api.x.ai/v1)
  - LM Studio (local)    (http://localhost:1234/v1)
  - Azure OpenAI         (https://<resource>.openai.azure.com/openai/deployments/<deployment>)
  - Any other OpenAI-compat endpoint

The existing OpenAIProvider (ironclaw/providers/openai.py) also uses this
pattern; CompatProvider adds first-class support for the others with
sensible defaults per service name.
"""

from __future__ import annotations

import os
from typing import Any, AsyncIterator

from ironclaw.core.message import Message, Role, ToolCall
from ironclaw.exceptions import ProviderError
from ironclaw.providers.base import LLMProvider, LLMResponse


# Known services and their default base URLs / env var names
_SERVICES: dict[str, dict[str, str]] = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "env_key":  "GROQ_API_KEY",
        "default_model": "llama-3.3-70b-versatile",
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "env_key":  "MISTRAL_API_KEY",
        "default_model": "mistral-large-latest",
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "env_key":  "TOGETHER_API_KEY",
        "default_model": "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",
    },
    "perplexity": {
        "base_url": "https://api.perplexity.ai",
        "env_key":  "PERPLEXITY_API_KEY",
        "default_model": "sonar-pro",
    },
    "xai": {
        "base_url": "https://api.x.ai/v1",
        "env_key":  "XAI_API_KEY",
        "default_model": "grok-3",
    },
    "lmstudio": {
        "base_url": "http://localhost:1234/v1",
        "env_key":  "",
        "default_model": "local-model",
    },
    "fireworks": {
        "base_url": "https://api.fireworks.ai/inference/v1",
        "env_key":  "FIREWORKS_API_KEY",
        "default_model": "accounts/fireworks/models/llama-v3p1-405b-instruct",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "env_key":  "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
    },
    "cerebras": {
        "base_url": "https://api.cerebras.ai/v1",
        "env_key":  "CEREBRAS_API_KEY",
        "default_model": "llama3.1-70b",
    },
}


class CompatProvider(LLMProvider):
    """
    Generic OpenAI-compatible provider.

    Parameters
    ----------
    service : str
        One of the known service names in ``_SERVICES``, or ``"custom"``.
    api_key : str | None
        API key. Falls back to the env var defined for the service.
    model : str | None
        Model name. Falls back to the service default.
    base_url : str | None
        Override the endpoint URL (required when service == "custom").
    temperature : float
    max_tokens : int
    extra_headers : dict
        Any extra headers to send (e.g. Azure api-version).
    """

    def __init__(
        self,
        service: str = "groq",
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.service = service
        svc = _SERVICES.get(service, {})

        env_key = svc.get("env_key", "")
        self.api_key = api_key or (os.environ.get(env_key, "") if env_key else "dummy")
        self.model = model or svc.get("default_model", "gpt-4o")
        self.base_url = base_url or svc.get("base_url", "")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.extra_headers = extra_headers or {}

        if not self.base_url:
            raise ValueError(f"base_url required for service '{service}'")

    async def complete(
        self,
        messages: list[Message],
        tool_schemas: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise ProviderError(
                "openai package not installed. Run: pip install openai"
            ) from e

        client = AsyncOpenAI(
            api_key=self.api_key or "dummy",
            base_url=self.base_url,
            default_headers=self.extra_headers,
        )

        wire_messages = _build_wire_messages(messages)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": wire_messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tool_schemas:
            kwargs["tools"] = tool_schemas
            kwargs["tool_choice"] = "auto"

        try:
            resp = await client.chat.completions.create(**kwargs)
        except Exception as e:
            raise ProviderError(f"{self.service} API error: {e}") from e

        choice = resp.choices[0]
        msg = choice.message
        content = msg.content or ""
        tool_calls: list[ToolCall] = []

        if msg.tool_calls:
            import json
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    args = {}
                tool_calls.append(ToolCall(
                    tool_name=tc.function.name,
                    arguments=args,
                    call_id=tc.id,
                ))

        return LLMResponse(content=content, tool_calls=tool_calls)

    # ------------------------------------------------------------------
    # stream() — real token-by-token via OpenAI-compatible SSE stream
    # ------------------------------------------------------------------

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise ProviderError(
                "openai package not installed. Run: pip install openai"
            ) from e

        client = AsyncOpenAI(
            api_key=self.api_key or "dummy",
            base_url=self.base_url,
            default_headers=self.extra_headers,
        )

        wire_messages = _build_wire_messages(messages)

        call_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": wire_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        try:
            stream = await client.chat.completions.create(**call_kwargs)
        except Exception as e:
            raise ProviderError(f"{self.service} streaming API error: {e}") from e

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    @property
    def provider_name(self) -> str:
        return self.service


def _build_wire_messages(messages: list[Message]) -> list[dict]:
    wire = []
    for m in messages:
        if m.role == Role.SYSTEM:
            wire.append({"role": "system", "content": m.content or ""})
        elif m.role == Role.USER:
            wire.append({"role": "user", "content": m.content or ""})
        elif m.role == Role.ASSISTANT:
            wire.append({"role": "assistant", "content": m.content or ""})
        elif m.role == Role.TOOL_RESULT:
            wire.append({
                "role": "tool",
                "tool_call_id": m.tool_results[0].call_id if m.tool_results else "",
                "content": m.tool_results[0].output if m.tool_results else "",
            })
    return wire


# ---------------------------------------------------------------------------
# Convenience factory functions
# ---------------------------------------------------------------------------

def GroqProvider(model: str = "llama-3.3-70b-versatile", **kw) -> CompatProvider:
    return CompatProvider(service="groq", model=model, **kw)

def MistralProvider(model: str = "mistral-large-latest", **kw) -> CompatProvider:
    return CompatProvider(service="mistral", model=model, **kw)

def TogetherProvider(model: str = "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo", **kw) -> CompatProvider:
    return CompatProvider(service="together", model=model, **kw)

def PerplexityProvider(model: str = "sonar-pro", **kw) -> CompatProvider:
    return CompatProvider(service="perplexity", model=model, **kw)

def XAIProvider(model: str = "grok-3", **kw) -> CompatProvider:
    return CompatProvider(service="xai", model=model, **kw)

def LMStudioProvider(model: str = "local-model", host: str = "http://localhost:1234", **kw) -> CompatProvider:
    return CompatProvider(service="lmstudio", model=model, base_url=f"{host}/v1", **kw)

def FireworksProvider(model: str = "accounts/fireworks/models/llama-v3p1-405b-instruct", **kw) -> CompatProvider:
    return CompatProvider(service="fireworks", model=model, **kw)

def DeepSeekProvider(model: str = "deepseek-chat", **kw) -> CompatProvider:
    return CompatProvider(service="deepseek", model=model, **kw)

def CerebrasProvider(model: str = "llama3.1-70b", **kw) -> CompatProvider:
    return CompatProvider(service="cerebras", model=model, **kw)

"""
ironclaw.providers.factory
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Provider factory — build any supported LLM provider from a string name.

Usage::

    from ironclaw.providers.factory import make_provider

    provider = make_provider("anthropic", model="claude-sonnet-4-6")
    provider = make_provider("groq",      model="llama-3.3-70b-versatile")
    provider = make_provider("gemini",    model="gemini-2.5-flash")
    provider = make_provider("bedrock",   model="us.amazon.nova-pro-v1:0")
    provider = make_provider("ollama",    model="llama3")
    provider = make_provider("lmstudio",  model="phi3", base_url="http://localhost:1234")

Supported provider IDs
----------------------
Cloud (API key required)
  anthropic   — Anthropic Claude
  openai      — OpenAI GPT / o1 / o3
  gemini      — Google Gemini
  groq        — Groq fast inference
  mistral     — Mistral AI
  cohere      — Cohere Command
  together    — Together AI
  perplexity  — Perplexity Sonar
  xai         — xAI Grok
  fireworks   — Fireworks AI
  deepseek    — DeepSeek
  cerebras    — Cerebras
  bedrock     — AWS Bedrock (all models via Converse API)
  azure       — Azure OpenAI

Local (no API key)
  ollama      — Ollama (llama3, qwen2.5, phi3, …)
  lmstudio    — LM Studio (any GGUF model)
"""

from __future__ import annotations

from typing import Any

from ironclaw.providers.base import LLMProvider


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

PROVIDER_CATALOGUE: dict[str, dict[str, str]] = {
    "anthropic":  {"class": "AnthropicProvider",  "module": "ironclaw.providers.anthropic",
                   "default_model": "claude-sonnet-4-6",
                   "description": "Anthropic Claude — claude-sonnet-4-6, claude-opus-4-6, haiku"},
    "openai":     {"class": "OpenAIProvider",      "module": "ironclaw.providers.openai",
                   "default_model": "gpt-4o",
                   "description": "OpenAI — gpt-4o, o1, o3, gpt-4o-mini"},
    "gemini":     {"class": "GeminiProvider",      "module": "ironclaw.providers.gemini",
                   "default_model": "gemini-2.5-flash",
                   "description": "Google Gemini — gemini-2.5-pro, gemini-2.5-flash"},
    "groq":       {"class": "CompatProvider",      "module": "ironclaw.providers.compat",
                   "default_model": "llama-3.3-70b-versatile",
                   "description": "Groq — llama-3.3-70b, mixtral (ultra-fast inference)"},
    "mistral":    {"class": "CompatProvider",      "module": "ironclaw.providers.compat",
                   "default_model": "mistral-large-latest",
                   "description": "Mistral AI — mistral-large, mistral-small, codestral"},
    "cohere":     {"class": "CohereProvider",      "module": "ironclaw.providers.cohere",
                   "default_model": "command-r-plus",
                   "description": "Cohere — command-r-plus, command-r"},
    "together":   {"class": "CompatProvider",      "module": "ironclaw.providers.compat",
                   "default_model": "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",
                   "description": "Together AI — llama-3.1-405b, qwen2.5, many open models"},
    "perplexity": {"class": "CompatProvider",      "module": "ironclaw.providers.compat",
                   "default_model": "sonar-pro",
                   "description": "Perplexity — sonar-pro, sonar-reasoning (web-augmented)"},
    "xai":        {"class": "CompatProvider",      "module": "ironclaw.providers.compat",
                   "default_model": "grok-3",
                   "description": "xAI Grok — grok-3, grok-3-mini"},
    "fireworks":  {"class": "CompatProvider",      "module": "ironclaw.providers.compat",
                   "default_model": "accounts/fireworks/models/llama-v3p1-405b-instruct",
                   "description": "Fireworks AI — llama, qwen, deepseek (fast open-model inference)"},
    "deepseek":   {"class": "CompatProvider",      "module": "ironclaw.providers.compat",
                   "default_model": "deepseek-chat",
                   "description": "DeepSeek — deepseek-chat, deepseek-reasoner"},
    "cerebras":   {"class": "CompatProvider",      "module": "ironclaw.providers.compat",
                   "default_model": "llama3.1-70b",
                   "description": "Cerebras — llama3.1-70b (wafer-scale inference)"},
    "bedrock":    {"class": "BedrockProvider",     "module": "ironclaw.providers.bedrock",
                   "default_model": "us.anthropic.claude-sonnet-4-6-20250514-v1:0",
                   "description": "AWS Bedrock — Claude, Llama, Nova (all models via Converse API)"},
    "azure":      {"class": "CompatProvider",      "module": "ironclaw.providers.compat",
                   "default_model": "gpt-4o",
                   "description": "Azure OpenAI — your deployed GPT-4o / o1 / o3 endpoint"},
    "ollama":     {"class": "OllamaProvider",      "module": "ironclaw.providers.ollama",
                   "default_model": "llama3",
                   "description": "Ollama (local) — llama3, qwen2.5, phi3, mistral, gemma"},
    "lmstudio":   {"class": "CompatProvider",      "module": "ironclaw.providers.compat",
                   "default_model": "local-model",
                   "description": "LM Studio (local) — any GGUF model via local server"},
}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_provider(
    provider_id: str,
    model: str | None = None,
    api_key: str | None = None,
    **kwargs: Any,
) -> LLMProvider:
    """
    Instantiate a provider by name.

    Parameters
    ----------
    provider_id :
        One of the IDs in ``PROVIDER_CATALOGUE``.
    model :
        Override the default model for this provider.
    api_key :
        API key (most providers also accept their own env var).
    **kwargs :
        Passed directly to the provider constructor (e.g. base_url, region).
    """
    if provider_id not in PROVIDER_CATALOGUE:
        supported = ", ".join(sorted(PROVIDER_CATALOGUE))
        raise ValueError(
            f"Unknown provider '{provider_id}'. Supported: {supported}"
        )

    info = PROVIDER_CATALOGUE[provider_id]
    module_name = info["module"]
    class_name  = info["class"]
    default_model = info["default_model"]

    import importlib
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)

    # CompatProvider needs the `service` kwarg
    if class_name == "CompatProvider":
        kwargs.setdefault("service", provider_id)

    # Special case: Azure needs base_url from env if not provided
    if provider_id == "azure" and "base_url" not in kwargs:
        import os
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        if endpoint:
            deploy = model or default_model
            kwargs["base_url"] = f"{endpoint.rstrip('/')}/openai/deployments/{deploy}"
            kwargs.setdefault("extra_headers", {"api-key": api_key or os.environ.get("AZURE_OPENAI_API_KEY", "")})

    ctor_kwargs: dict[str, Any] = {"model": model or default_model}
    if api_key:
        ctor_kwargs["api_key"] = api_key
    ctor_kwargs.update(kwargs)

    return cls(**ctor_kwargs)


def list_providers() -> list[dict[str, str]]:
    """Return the provider catalogue as a list of dicts for display."""
    return [
        {"id": pid, "default_model": info["default_model"], "description": info["description"]}
        for pid, info in PROVIDER_CATALOGUE.items()
    ]

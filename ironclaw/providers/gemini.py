"""
ironclaw.providers.gemini
~~~~~~~~~~~~~~~~~~~~~~~~~~
Google Gemini provider via the `google-generativeai` SDK.

Install:  pip install google-generativeai

Supported models (May 2026):
  gemini-2.5-pro             — strongest reasoning + long context
  gemini-2.5-flash           — fast, cost-efficient
  gemini-2.0-flash           — balanced
  gemini-1.5-pro             — 1M context window
"""

from __future__ import annotations

import os
from typing import Any

from ironclaw.core.message import Message, Role, ToolCall
from ironclaw.exceptions import ProviderError
from ironclaw.providers.base import LLMProvider, LLMResponse

_DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiProvider(LLMProvider):
    """
    Google Gemini via google-generativeai SDK.

    Parameters
    ----------
    api_key : str | None
        Defaults to ``GEMINI_API_KEY`` env var.
    model : str
        Gemini model name (default: gemini-2.5-flash).
    temperature : float
        Sampling temperature.
    max_tokens : int
        Max output tokens.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = _DEFAULT_MODEL,
        temperature: float = 0.7,
        max_tokens: int = 8192,
    ) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def complete(
        self,
        messages: list[Message],
        tool_schemas: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        try:
            import google.generativeai as genai
        except ImportError as e:
            raise ProviderError(
                "google-generativeai not installed. Run: pip install google-generativeai"
            ) from e

        if not self.api_key:
            raise ProviderError("GEMINI_API_KEY not set")

        genai.configure(api_key=self.api_key)

        # Extract system prompt
        system_parts = [m.content for m in messages if m.role == Role.SYSTEM]
        system_instruction = "\n\n".join(system_parts) if system_parts else None

        # Build history (Gemini uses a different format)
        history = []
        for m in messages:
            if m.role == Role.SYSTEM:
                continue
            if m.role == Role.USER:
                history.append({"role": "user", "parts": [m.content or ""]})
            elif m.role == Role.ASSISTANT:
                history.append({"role": "model", "parts": [m.content or ""]})

        # Build tool declarations
        tools_arg = None
        if tool_schemas:
            fn_decls = []
            for schema in tool_schemas:
                fn = schema.get("function", schema)
                params = fn.get("parameters", {})
                fn_decls.append({
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "parameters": params,
                })
            tools_arg = [{"function_declarations": fn_decls}]

        gen_config = genai.GenerationConfig(
            temperature=self.temperature,
            max_output_tokens=self.max_tokens,
        )

        model_kwargs: dict[str, Any] = {"generation_config": gen_config}
        if system_instruction:
            model_kwargs["system_instruction"] = system_instruction
        if tools_arg:
            model_kwargs["tools"] = tools_arg

        try:
            client = genai.GenerativeModel(self.model, **model_kwargs)
            # Separate last user message from history
            if history and history[-1]["role"] == "user":
                last_msg = history[-1]["parts"][0]
                chat_history = history[:-1]
            else:
                last_msg = ""
                chat_history = history

            chat = client.start_chat(history=chat_history)
            response = chat.send_message(last_msg)
        except Exception as e:
            raise ProviderError(f"Gemini API error: {e}") from e

        # Parse tool calls if any
        tool_calls: list[ToolCall] = []
        text_content = ""

        candidate = response.candidates[0] if response.candidates else None
        if candidate:
            for part in candidate.content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    tool_calls.append(ToolCall(
                        tool_name=fc.name,
                        arguments=dict(fc.args),
                        call_id=f"gemini_{fc.name}",
                    ))
                elif hasattr(part, "text"):
                    text_content += part.text

        return LLMResponse(content=text_content, tool_calls=tool_calls)

    @property
    def provider_name(self) -> str:
        return "gemini"

"""
ironclaw.providers.bedrock
~~~~~~~~~~~~~~~~~~~~~~~~~~~
AWS Bedrock provider via boto3.

Install:  pip install boto3

Credentials are loaded from the standard boto3 chain:
  1. Environment: AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY + AWS_DEFAULT_REGION
  2. ~/.aws/credentials
  3. IAM instance role

Supported model IDs (cross-region inference):
  us.anthropic.claude-sonnet-4-6-20250514-v1:0
  us.anthropic.claude-opus-4-6-20260101-v1:0
  us.meta.llama3-3-70b-instruct-v1:0
  us.amazon.nova-pro-v1:0
  us.amazon.nova-lite-v1:0
  (and any model deployed in your region)
"""

from __future__ import annotations

import json
import os
from typing import Any

from ironclaw.core.message import Message, Role, ToolCall
from ironclaw.exceptions import ProviderError
from ironclaw.providers.base import LLMProvider, LLMResponse

_DEFAULT_MODEL = "us.anthropic.claude-sonnet-4-6-20250514-v1:0"
_DEFAULT_REGION = "us-east-1"


class BedrockProvider(LLMProvider):
    """
    AWS Bedrock Converse API provider.

    Uses the unified ``converse`` API which works across all Bedrock models
    and supports tool use natively.

    Parameters
    ----------
    model_id : str
        Bedrock model ID. Defaults to Claude Sonnet (cross-region).
    region : str
        AWS region name. Defaults to ``AWS_DEFAULT_REGION`` or us-east-1.
    profile : str | None
        AWS named profile to use (optional).
    temperature : float
    max_tokens : int
    """

    def __init__(
        self,
        model_id: str = _DEFAULT_MODEL,
        region: str | None = None,
        profile: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> None:
        self.model_id = model_id
        self.region = region or os.environ.get("AWS_DEFAULT_REGION", _DEFAULT_REGION)
        self.profile = profile
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def complete(
        self,
        messages: list[Message],
        tool_schemas: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        try:
            import boto3
        except ImportError as e:
            raise ProviderError("boto3 not installed. Run: pip install boto3") from e

        import asyncio
        return await asyncio.to_thread(self._complete_sync, messages, tool_schemas)

    def _complete_sync(
        self,
        messages: list[Message],
        tool_schemas: list[dict[str, Any]] | None,
    ) -> LLMResponse:
        import boto3

        session_kwargs: dict[str, Any] = {"region_name": self.region}
        if self.profile:
            session_kwargs["profile_name"] = self.profile

        session = boto3.Session(**session_kwargs)
        client = session.client("bedrock-runtime")

        # System prompt
        system_parts = [{"text": m.content} for m in messages if m.role == Role.SYSTEM and m.content]

        # Conversation turns
        converse_msgs = []
        for m in messages:
            if m.role == Role.SYSTEM:
                continue
            if m.role == Role.USER:
                converse_msgs.append({"role": "user", "content": [{"text": m.content or ""}]})
            elif m.role == Role.ASSISTANT:
                converse_msgs.append({"role": "assistant", "content": [{"text": m.content or ""}]})
            elif m.role == Role.TOOL_RESULT and m.tool_results:
                for tr in m.tool_results:
                    converse_msgs.append({
                        "role": "user",
                        "content": [{
                            "toolResult": {
                                "toolUseId": tr.call_id,
                                "content": [{"text": str(tr.output)}],
                            }
                        }],
                    })

        kwargs: dict[str, Any] = {
            "modelId": self.model_id,
            "messages": converse_msgs,
            "inferenceConfig": {
                "temperature": self.temperature,
                "maxTokens": self.max_tokens,
            },
        }
        if system_parts:
            kwargs["system"] = system_parts
        if tool_schemas:
            # Convert OpenAI tool schema to Bedrock toolSpec
            tool_specs = []
            for schema in tool_schemas:
                fn = schema.get("function", schema)
                tool_specs.append({
                    "toolSpec": {
                        "name": fn["name"],
                        "description": fn.get("description", ""),
                        "inputSchema": {"json": fn.get("parameters", {})},
                    }
                })
            kwargs["toolConfig"] = {"tools": tool_specs}

        try:
            resp = client.converse(**kwargs)
        except Exception as e:
            raise ProviderError(f"Bedrock API error: {e}") from e

        content = ""
        tool_calls: list[ToolCall] = []
        output_msg = resp.get("output", {}).get("message", {})
        for block in output_msg.get("content", []):
            if "text" in block:
                content += block["text"]
            elif "toolUse" in block:
                tu = block["toolUse"]
                tool_calls.append(ToolCall(
                    tool_name=tu["name"],
                    arguments=tu.get("input", {}),
                    call_id=tu["toolUseId"],
                ))

        return LLMResponse(content=content, tool_calls=tool_calls)

    @property
    def provider_name(self) -> str:
        return "bedrock"

"""
ironclaw.ace.orchestrator
~~~~~~~~~~~~~~~~~~~~~~~~~
Agent Creation Engine — Creator Agent.

The Creator Agent is a specialised orchestrator agent whose sole job is
to help users define and spawn new agents through natural conversation.

It has exactly ONE tool: ``spawn_new_agent``.  This narrow capability
surface is intentional — it limits blast radius if the agent is ever
manipulated by adversarial input.

Usage
-----
::

    from ironclaw.ace.orchestrator import build_creator_agent

    creator = build_creator_agent(provisioner, provider_id="anthropic")
    response = await creator.chat("Create a customer support bot using GPT-4o")
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from ironclaw.ace.schema import AgentSpec

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt for the Creator Agent
# ---------------------------------------------------------------------------

CREATOR_SYSTEM_PROMPT = """\
You are the IronClaw Creator Agent — a specialised AI whose only job is to \
help users design and provision new agents inside the IronClaw framework.

## Your capabilities
You have ONE tool: `spawn_new_agent`. Use it to create agents once you have \
gathered enough information from the user. Do not attempt any other actions.

## Conversation flow
1. **Discover intent** — Ask the user what they want the agent to do.
2. **Clarify requirements** — Ask targeted follow-up questions:
   - What LLM provider / model should it use?
   - What tools does it need? (web search, file access, shell, custom)
   - Does it need persistent memory?
   - Who will interact with it? (CLI, gateway, API)
   - Any security constraints?
3. **Confirm before creating** — Summarise your understanding and ask \
   the user to confirm before calling `spawn_new_agent`.
4. **Provide post-creation guidance** — After creation, tell the user:
   - The agent ID
   - How to chat with it (`ironclaw agent chat <id>`)
   - Any warnings encountered during provisioning

## Rules
- NEVER embed plaintext API keys. Always use `env:VAR_NAME` references.
- NEVER create agents without explicit user confirmation.
- If the user asks you to do something unrelated to agent creation, politely \
  explain that your role is limited to designing and provisioning agents.
- Keep questions concise. One or two questions per turn maximum.
- Default provider is anthropic with claude-sonnet-4-6 unless the user asks \
  for something else.
- Default tools: none (ask the user what they need).
- Default memory: in_memory.
- Default isolation: none.

## AgentSpec format reminder
When calling `spawn_new_agent`, build the spec carefully:
- `agentId`: lowercase, hyphens only, 1–64 chars
- `model.credentials`: use `"env:VARNAME"` pattern
- `security.capabilities`: grant only what the tools need
  - web tools  → ["web:search", "web:fetch"]
  - filesystem → ["file:read", "file:write"]
  - shell      → ["shell:execute"]
- `isolation`: prefer "none" unless the user explicitly asks for sandboxing

Be helpful, be concise, and always put security first.
"""

# ---------------------------------------------------------------------------
# spawn_new_agent tool schema
# ---------------------------------------------------------------------------

SPAWN_TOOL_SCHEMA: Dict[str, Any] = {
    "name": "spawn_new_agent",
    "description": (
        "Provision a new IronClaw agent from an AgentSpec. "
        "Call this only after gathering requirements from the user and receiving their confirmation."
    ),
    "input_schema": {
        "type": "object",
        "required": ["spec"],
        "properties": {
            "spec": {
                "type": "object",
                "description": "The complete AgentSpec JSON object",
                "required": ["agentId", "model"],
                "properties": {
                    "agentId": {
                        "type": "string",
                        "description": "Unique agent ID (lowercase alphanumeric + hyphens)",
                    },
                    "persona": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "systemPrompt": {"type": "string"},
                        },
                    },
                    "model": {
                        "type": "object",
                        "required": ["provider"],
                        "properties": {
                            "provider": {
                                "type": "string",
                                "description": (
                                    "Provider ID: anthropic, openai, gemini, cohere, bedrock, "
                                    "groq, mistral, together, perplexity, xai, fireworks, "
                                    "deepseek, cerebras, lmstudio, ollama"
                                ),
                            },
                            "model": {
                                "type": "string",
                                "description": "Model identifier (omit to use provider default)",
                            },
                            "credentials": {
                                "type": "object",
                                "description": "Credential refs — values must be 'env:VAR'",
                                "additionalProperties": {"type": "string"},
                            },
                            "parameters": {
                                "type": "object",
                                "description": "Extra provider kwargs (base_url, timeout, etc.)",
                            },
                        },
                    },
                    "tools": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["name"],
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "enum": ["web", "filesystem", "shell"],
                                },
                                "enabled": {"type": "boolean", "default": True},
                                "config": {"type": "object"},
                            },
                        },
                    },
                    "skills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Skill names to load (e.g. 'web-research', 'code-executor')",
                    },
                    "memory": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["in_memory", "sqlite", "none"],
                                "default": "in_memory",
                            },
                            "dbPath": {"type": "string"},
                            "sessionId": {"type": "string"},
                        },
                    },
                    "security": {
                        "type": "object",
                        "properties": {
                            "capabilities": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Capability tokens e.g. ['web:search', 'file:read']",
                            },
                            "guardBlockThreshold": {"type": "number", "default": 0.75},
                            "guardWarnThreshold": {"type": "number", "default": 0.45},
                        },
                    },
                    "isolation": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["none", "subprocess", "docker"],
                                "default": "none",
                            },
                            "image": {"type": "string"},
                        },
                    },
                    "metadata": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "tags": {"type": "array", "items": {"type": "string"}},
                            "owner": {"type": "string"},
                        },
                    },
                },
            },
            "dry_run": {
                "type": "boolean",
                "default": False,
                "description": "If true, validate and plan without creating the agent",
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------

async def execute_spawn_tool(
    tool_input: Dict[str, Any],
    provisioner,
) -> Dict[str, Any]:
    """
    Execute the ``spawn_new_agent`` tool call.

    Returns a dict that will be serialised to JSON and returned to the LLM
    as the tool result.
    """
    try:
        spec_data = tool_input.get("spec", {})
        dry_run   = tool_input.get("dry_run", False)

        # Parse into AgentSpec (validates schema)
        spec = AgentSpec.from_dict(spec_data)

        if dry_run:
            plan = await provisioner.dry_run(spec)
            return {
                "status":  "dry_run_ok",
                "plan":    plan,
                "message": (
                    f"Dry run successful for agent '{spec.agentId}'. "
                    f"No resources were created. Warnings: {plan.get('warnings', [])}"
                ),
            }

        result = await provisioner.provision(spec)
        return {
            "status":   "created",
            "agentId":  result.agent_id,
            "warnings": result.warnings,
            "message":  (
                f"Agent '{result.agent_id}' provisioned successfully. "
                + (f"Warnings: {result.warnings}" if result.warnings else "")
            ),
        }

    except Exception as exc:
        log.exception("spawn_new_agent failed")
        return {
            "status":  "error",
            "error":   str(exc),
            "message": f"Failed to create agent: {exc}",
        }


# ---------------------------------------------------------------------------
# Creator Agent factory
# ---------------------------------------------------------------------------

def build_creator_agent(provisioner, provider_id: str = "anthropic", model: str | None = None):
    """
    Build the Creator Agent — a specialised Agent wired with the
    ``spawn_new_agent`` tool and the creator system prompt.

    Parameters
    ----------
    provisioner:
        An ``AgentProvisioner`` instance (shared with the server).
    provider_id:
        Which provider to use for the Creator Agent itself.
    model:
        Override the default model for this provider.

    Returns
    -------
    ironclaw.core.agent.Agent
        A fully built agent ready to receive chat messages.
    """
    from ironclaw.tools.registry import ToolRegistry
    from ironclaw.tools.permissions import CapabilitySet
    from ironclaw.core.agent import Agent
    from ironclaw.memory.conversation import InMemoryConversation
    from ironclaw.security.guard import PromptGuard
    from ironclaw.tools.sandbox import Sandbox
    from ironclaw.providers.factory import make_provider

    # Build provider for the Creator Agent
    provider = make_provider(provider_id, model=model)

    # Register the single spawn_new_agent tool
    registry = ToolRegistry()

    async def _spawn(spec: dict, dry_run: bool = False) -> str:
        result = await execute_spawn_tool({"spec": spec, "dry_run": dry_run}, provisioner)
        return json.dumps(result, indent=2)

    from ironclaw.tools.registry import ToolSpec
    registry.register(ToolSpec(
        name="spawn_new_agent",
        description=SPAWN_TOOL_SCHEMA["description"],
        fn=_spawn,
        schema=SPAWN_TOOL_SCHEMA["input_schema"],
        capabilities_required=["ace:spawn"],
        dangerous=False,
    ))

    return Agent(
        agent_id="creator-agent",
        name="IronClaw Creator Agent",
        system_prompt=CREATOR_SYSTEM_PROMPT,
        provider=provider,
        tools=registry,
        capabilities=CapabilitySet(["ace:spawn"]),
        memory=InMemoryConversation(),
        guard=PromptGuard(),
        sandbox=Sandbox(),
        max_iterations=15,
    )

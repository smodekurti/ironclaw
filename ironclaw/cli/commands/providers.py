"""
ironclaw.cli.commands.providers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``ironclaw providers`` subcommand tree.

Commands
--------
ironclaw providers list
    Show all supported LLM providers, their default models, and status
    (whether the required API key env var is set).

ironclaw providers test <provider_id>
    Send a short test message to confirm the provider is reachable and
    credentials are valid.
"""

from __future__ import annotations

import argparse
import asyncio
import os

from ironclaw.cli import fmt


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------

def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("providers", help="List and test LLM providers")
    s = p.add_subparsers(dest="providers_cmd", metavar="<command>")
    s.required = True

    s.add_parser("list", help="List all supported providers")

    pt = s.add_parser("test", help="Send a test message to a provider")
    pt.add_argument("provider_id", help="Provider to test (e.g. anthropic, groq, ollama)")
    pt.add_argument("--model",   default=None,  help="Override model")
    pt.add_argument("--api-key", default=None,  dest="api_key", help="Override API key")


# ---------------------------------------------------------------------------
# Dispatch (no server required — talks directly to the LLM)
# ---------------------------------------------------------------------------

def dispatch(args: argparse.Namespace, _client: object) -> int:
    cmd = args.providers_cmd
    as_json = getattr(args, "json", False)

    if cmd == "list":
        return _list(as_json)
    if cmd == "test":
        return _test(args, as_json)

    fmt.error(f"Unknown providers command: {cmd}")
    return 1


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------

_ENV_KEYS = {
    "anthropic":  "ANTHROPIC_API_KEY",
    "openai":     "OPENAI_API_KEY",
    "gemini":     "GEMINI_API_KEY",
    "groq":       "GROQ_API_KEY",
    "mistral":    "MISTRAL_API_KEY",
    "cohere":     "COHERE_API_KEY",
    "together":   "TOGETHER_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
    "xai":        "XAI_API_KEY",
    "fireworks":  "FIREWORKS_API_KEY",
    "deepseek":   "DEEPSEEK_API_KEY",
    "cerebras":   "CEREBRAS_API_KEY",
    "bedrock":    "AWS_ACCESS_KEY_ID",
    "azure":      "AZURE_OPENAI_API_KEY",
    "ollama":     "",    # no key needed
    "lmstudio":   "",    # no key needed
}


def _list(as_json: bool) -> int:
    from ironclaw.providers.factory import list_providers

    providers = list_providers()

    if as_json:
        fmt.json_out(providers)
        return 0

    fmt.section("Supported LLM Providers")
    print()

    rows = []
    for p in providers:
        pid = p["id"]
        env_var = _ENV_KEYS.get(pid, "")
        if not env_var:
            configured = fmt.colored("local", "bcyan")
        elif os.environ.get(env_var):
            configured = fmt.colored("✓ configured", "bgreen")
        else:
            configured = fmt.colored("✗ not set", "red") + fmt.dim(f"  ({env_var})")

        rows.append([
            fmt.bold(pid),
            p["default_model"],
            configured,
        ])

    fmt.table(
        rows,
        headers=["provider", "default model", "status"],
        col_widths=[14, 50, 40],
    )
    print()
    fmt.info("Set the relevant API key env var or run: ironclaw setup")
    return 0


def _test(args: argparse.Namespace, as_json: bool) -> int:
    from ironclaw.providers.factory import make_provider
    from ironclaw.core.message import Message, Role

    pid = args.provider_id
    fmt.info(f"Testing provider: {fmt.bold(pid)}")

    try:
        provider = make_provider(pid, model=args.model, api_key=args.api_key)
    except ValueError as e:
        fmt.error(str(e))
        return 1

    messages = [
        Message.system("You are a helpful assistant."),
        Message.user("Reply with exactly: IRONCLAW_TEST_OK"),
    ]

    fmt.info(f"Sending test message to {pid} ({provider.model})…")

    try:
        resp = asyncio.run(provider.complete(messages))
    except Exception as e:
        fmt.error(f"Provider error: {e}")
        return 1

    content = resp.content.strip()

    if as_json:
        fmt.json_out({"provider": pid, "model": provider.model, "response": content})
        return 0

    if "IRONCLAW_TEST_OK" in content:
        fmt.success(f"{pid} is working correctly (model: {provider.model})")
    else:
        fmt.warn(f"Unexpected response: {content[:120]}")
        fmt.info("Provider reached but returned an unexpected answer — it's likely fine.")

    return 0

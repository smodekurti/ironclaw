"""
ironclaw.cli.commands.setup
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Interactive first-run setup wizard.

  ironclaw setup

Walks the user through:
  1. Choosing LLM providers and entering API keys
  2. Enabling built-in skills
  3. Configuring gateway connections (optional)
  4. Writing ironclaw.toml and a .env file
  5. Starting the server
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ironclaw.cli import fmt

# ---------------------------------------------------------------------------
# Provider catalogue
# ---------------------------------------------------------------------------

PROVIDERS = [
    # (id, display_name, env_var, notes)
    ("anthropic",   "Anthropic Claude",    "ANTHROPIC_API_KEY",    "claude-sonnet-4-6, claude-opus-4-6, haiku"),
    ("openai",      "OpenAI",              "OPENAI_API_KEY",       "gpt-4o, o1, o3"),
    ("gemini",      "Google Gemini",       "GEMINI_API_KEY",       "gemini-2.5-pro, gemini-flash"),
    ("groq",        "Groq",                "GROQ_API_KEY",         "llama-3.3-70b, mixtral-8x7b — fast inference"),
    ("mistral",     "Mistral AI",          "MISTRAL_API_KEY",      "mistral-large, mistral-small"),
    ("cohere",      "Cohere",              "COHERE_API_KEY",       "command-r-plus, command-r"),
    ("together",    "Together AI",         "TOGETHER_API_KEY",     "llama-3.1-405b, qwen2.5"),
    ("perplexity",  "Perplexity",          "PERPLEXITY_API_KEY",   "sonar-pro, sonar-reasoning"),
    ("xai",         "xAI Grok",            "XAI_API_KEY",          "grok-3, grok-3-mini"),
    ("bedrock",     "AWS Bedrock",         "AWS_ACCESS_KEY_ID",    "claude-3-5-sonnet, llama-3-70b (via AWS)"),
    ("azure",       "Azure OpenAI",        "AZURE_OPENAI_API_KEY", "your deployed GPT-4o, o1 endpoint"),
    ("ollama",      "Ollama (local)",      "",                     "llama3, qwen2.5, phi3 — runs locally"),
    ("lmstudio",    "LM Studio (local)",   "",                     "any GGUF model — runs locally"),
]

BUILTIN_SKILLS = [
    ("web-research",        "Search the web and synthesise answers from multiple sources"),
    ("code-executor",       "Write and run Python / Bash code, return output"),
    ("data-analyst",        "Analyse CSV/JSON data, produce summaries and statistics"),
    ("email-drafter",       "Draft professional emails with tone and audience control"),
    ("document-summarizer", "Summarise long documents into concise, structured notes"),
    ("image-analyzer",      "Describe and analyse images (requires vision model)"),
]

# ---------------------------------------------------------------------------
# Wizard helpers
# ---------------------------------------------------------------------------

def _ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    try:
        val = input(f"  {prompt}{hint}: ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(0)
    return val or default


def _ask_yn(prompt: str, default: bool = False) -> bool:
    hint = "(Y/n)" if default else "(y/N)"
    try:
        val = input(f"  {prompt} {hint}: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(0)
    if not val:
        return default
    return val.startswith("y")


def _choose_many(items: list[tuple[str, str]], prompt: str) -> list[str]:
    """Show a numbered list and let the user pick by number (space-separated) or 'all'/'none'."""
    print()
    for i, (key, label) in enumerate(items, 1):
        print(f"    {fmt.colored(str(i).rjust(2), 'bcyan')}  {fmt.bold(key):<28}  {fmt.dim(label)}")
    print()
    try:
        raw = input(f"  {prompt} (numbers, 'all', or Enter to skip): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(0)
    if not raw or raw == "none":
        return []
    if raw == "all":
        return [k for k, _ in items]
    chosen = []
    for token in raw.replace(",", " ").split():
        try:
            idx = int(token) - 1
            if 0 <= idx < len(items):
                chosen.append(items[idx][0])
        except ValueError:
            pass
    return chosen

# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------

def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("setup", help="Interactive first-run setup wizard")
    p.add_argument("--non-interactive", action="store_true",
                   help="Skip wizard and just write defaults")


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------

def dispatch(args: argparse.Namespace, _client: object) -> int:
    print()
    print(fmt.bold("  ╔══════════════════════════════════╗"))
    print(fmt.bold("  ║    IronClaw Setup Wizard         ║"))
    print(fmt.bold("  ╚══════════════════════════════════╝"))
    print()
    fmt.info("This wizard configures IronClaw and writes ironclaw.toml + .env")
    fmt.info("You can re-run it at any time with: ironclaw setup")
    print()

    if getattr(args, "non_interactive", False):
        return _write_defaults()

    env: dict[str, str] = {}
    toml: dict = {}

    # ── Step 1: Providers ────────────────────────────────────────────────────
    fmt.section("Step 1 of 4 — LLM Providers")
    fmt.info("Choose which providers to configure:")

    provider_items = [(p[0], f"{p[1]}  —  {p[3]}") for p in PROVIDERS]
    chosen_providers = _choose_many(provider_items, "Select providers")

    default_provider = ""
    default_model = ""

    for pid in chosen_providers:
        pdata = next(p for p in PROVIDERS if p[0] == pid)
        _, name, env_var, notes = pdata

        print()
        print(f"  {fmt.bold(name)}")

        if pid == "ollama":
            host = _ask("Ollama host", "http://localhost:11434")
            model = _ask("Default model", "llama3")
            env["OLLAMA_HOST"] = host
            if not default_provider:
                default_provider = "ollama"
                default_model = model

        elif pid == "lmstudio":
            host = _ask("LM Studio host", "http://localhost:1234")
            model = _ask("Model name (from LM Studio)", "local-model")
            env["LMSTUDIO_HOST"] = host
            if not default_provider:
                default_provider = "lmstudio"
                default_model = model

        elif pid == "bedrock":
            env["AWS_ACCESS_KEY_ID"] = _ask("AWS Access Key ID")
            env["AWS_SECRET_ACCESS_KEY"] = _ask("AWS Secret Access Key")
            env["AWS_DEFAULT_REGION"] = _ask("AWS Region", "us-east-1")
            model = _ask("Default model", "us.anthropic.claude-sonnet-4-6-20250514-v1:0")
            if not default_provider:
                default_provider = "bedrock"
                default_model = model

        elif pid == "azure":
            env["AZURE_OPENAI_API_KEY"] = _ask("Azure OpenAI API Key")
            env["AZURE_OPENAI_ENDPOINT"] = _ask("Azure endpoint (https://...openai.azure.com)")
            model = _ask("Deployment name", "gpt-4o")
            if not default_provider:
                default_provider = "azure"
                default_model = model

        else:
            key = _ask(f"{env_var}")
            if key:
                env[env_var] = key
                suggested_model = {
                    "anthropic":  "claude-sonnet-4-6",
                    "openai":     "gpt-4o",
                    "gemini":     "gemini-2.5-pro",
                    "groq":       "llama-3.3-70b-versatile",
                    "mistral":    "mistral-large-latest",
                    "cohere":     "command-r-plus",
                    "together":   "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",
                    "perplexity": "sonar-pro",
                    "xai":        "grok-3",
                }.get(pid, "")
                model = _ask("Default model", suggested_model)
                if not default_provider:
                    default_provider = pid
                    default_model = model

    toml["defaults"] = {
        "provider": default_provider or "anthropic",
        "model":    default_model    or "claude-sonnet-4-6",
    }

    # ── Step 2: Skills ───────────────────────────────────────────────────────
    fmt.section("Step 2 of 4 — Built-in Skills")
    fmt.info("Skills extend agent capabilities with specialised knowledge.")
    fmt.info("Choose which built-in skills to enable:")

    chosen_skills = _choose_many(BUILTIN_SKILLS, "Select skills")
    toml["skills"] = {"enabled": chosen_skills}

    # ── Step 3: User profile ─────────────────────────────────────────────────
    fmt.section("Step 3 of 5 — Your User Profile")
    fmt.info(
        "The user profile tells every agent who you are and how to behave with you.\n"
        "  This is stored at ~/.ironclaw/user_profile.json and applied automatically."
    )
    print()
    setup_profile = _ask("Set up your user profile now? [Y/n]", "Y")
    if setup_profile.strip().lower() not in ("n", "no"):
        _setup_user_profile()

    # ── Step 4: Server ───────────────────────────────────────────────────────
    fmt.section("Step 4 of 5 — Server")
    host = _ask("Server host", "127.0.0.1")
    port = _ask("Server port", "7432")
    toml["server"] = {"host": host, "port": int(port)}

    audit_path = _ask("Audit log path", "logs/audit.jsonl")
    hmac = _ask("Audit HMAC secret (empty to skip signing)", "")
    toml["audit"] = {"log_path": audit_path}
    if hmac:
        env["IRONCLAW_AUDIT_SECRET"] = hmac

    # Auto-generate API key
    api_key = __import__("secrets").token_hex(32)
    env["IRONCLAW_API_KEY"] = api_key
    fmt.success("Generated secure IRONCLAW_API_KEY for the Web API.")
    print()

    # ── Step 4.5: Gateways ──────────────────────────────────────────────────
    fmt.section("Step 4.5 of 5 — Gateways (Optional)")
    setup_gw = _ask_yn("Set up a messaging gateway now? (Telegram / WhatsApp / iMessage)", False)
    if setup_gw:
        gw_type = _ask("Gateway type [telegram / whatsapp / imessage]").lower()
        if gw_type == "telegram":
            env["TELEGRAM_BOT_TOKEN"] = _ask("Telegram Bot Token")
            fmt.info("Telegram gateway setup saved.")
        elif gw_type == "whatsapp":
            env["WHATSAPP_ACCESS_TOKEN"] = _ask("WhatsApp Access Token")
            fmt.info("WhatsApp requires webhook mode.")
        elif gw_type == "imessage":
            fmt.info("iMessage gateway relies on local database polling (macOS only).")

    # ── Step 5: Write files ───────────────────────────────────────────────────
    fmt.section("Step 5 of 5 — Writing configuration")
    return _write_config(toml, env)


def _setup_user_profile() -> None:
    """Interactive sub-wizard to populate the global user profile."""
    from ironclaw.user.profile import UserProfile
    from ironclaw.user.store import UserProfileStore

    store = UserProfileStore()
    profile = store.load()  # start from existing if re-running setup

    print()
    name = _ask("Your name", profile.name or "")
    role = _ask("Your role / job title", profile.role or "")
    org  = _ask("Organization (optional)", profile.organization or "")
    tz   = _ask("Timezone (e.g. America/New_York, optional)", profile.timezone or "")
    lang = _ask("Primary language for responses", profile.language or "English")

    print()
    fmt.info("Communication preferences (press Enter to skip each one):")
    tone      = _ask("Tone  [formal / casual / direct / friendly]", profile.preferences.get("tone", ""))
    verbosity = _ask("Verbosity  [low / medium / high]",           profile.preferences.get("verbosity", ""))
    expertise = _ask("Expertise level  [beginner / intermediate / expert]", profile.preferences.get("expertise_level", ""))

    print()
    fmt.info("Behavioural rules — 'always do' (one per line, blank line to finish):")
    dos = list(profile.dos)
    while True:
        rule = _ask("  + rule", "").strip()
        if not rule:
            break
        dos.append(rule)

    fmt.info("Behavioural rules — 'never do' (one per line, blank line to finish):")
    donts = list(profile.donts)
    while True:
        rule = _ask("  ✗ rule", "").strip()
        if not rule:
            break
        donts.append(rule)

    print()
    context = _ask("Any background about yourself agents should know (optional)", profile.context or "")

    prefs = dict(profile.preferences)
    if tone:      prefs["tone"] = tone
    if verbosity: prefs["verbosity"] = verbosity
    if expertise: prefs["expertise_level"] = expertise

    updated = UserProfile(
        name=name or profile.name,
        role=role or profile.role,
        organization=org or profile.organization,
        timezone=tz or profile.timezone,
        language=lang or profile.language,
        dos=dos,
        donts=donts,
        preferences=prefs,
        context=context or profile.context,
        goals=profile.goals,
        email=profile.email,
    )
    store.save(updated)
    print()
    fmt.success(f"User profile saved to {store.path}")
    fmt.dim("  Update it anytime with:  ironclaw user set / ironclaw user do / ironclaw user dont")


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------

def _write_defaults() -> int:
    return _write_config(
        toml={"server": {"host": "127.0.0.1", "port": 7432},
              "defaults": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
              "audit": {"log_path": "logs/audit.jsonl"},
              "skills": {"enabled": []}},
        env={},
    )


def _write_config(toml: dict, env: dict[str, str]) -> int:
    # Write ironclaw.toml
    config_path = Path("ironclaw.toml")
    lines = ["# ironclaw.toml — generated by `ironclaw setup`\n"]
    for section, vals in toml.items():
        lines.append(f"\n[{section}]\n")
        if isinstance(vals, dict):
            for k, v in vals.items():
                if isinstance(v, list):
                    lines.append(f'{k} = {_toml_list(v)}\n')
                elif isinstance(v, int):
                    lines.append(f'{k} = {v}\n')
                else:
                    lines.append(f'{k} = "{v}"\n')
        else:
            lines.append(f'value = "{vals}"\n')

    config_path.write_text("".join(lines), encoding="utf-8")
    fmt.success(f"Written {config_path}")

    # Write .env
    if env:
        env_path = Path(".env")
        existing: dict[str, str] = {}
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    existing[k.strip()] = v.strip()
        existing.update(env)
        env_path.write_text(
            "# IronClaw environment — generated by `ironclaw setup`\n" +
            "\n".join(f"{k}={v}" for k, v in existing.items()) + "\n",
            encoding="utf-8",
        )
        fmt.success(f"Written .env ({len(env)} key(s))")
        fmt.warn("Keep .env out of version control — add it to .gitignore")

    print()
    fmt.success("Setup complete!")
    print()
    print("  Start the server:    " + fmt.bold("ironclaw serve"))
    print("  Open the web UI:     " + fmt.bold("http://localhost:7432"))
    print("  Create an agent:     " + fmt.bold("ironclaw agent create --id mybot --provider anthropic"))
    print("  Chat with an agent:  " + fmt.bold("ironclaw agent chat mybot"))
    print("  View user profile:   " + fmt.bold("ironclaw user show"))
    print("  Add a rule:          " + fmt.bold('ironclaw user do "Always be concise"'))
    print()
    return 0


def _toml_list(items: list) -> str:
    quoted = ", ".join(f'"{i}"' for i in items)
    return f"[{quoted}]"

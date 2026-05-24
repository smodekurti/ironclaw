"""
ironclaw.cli.commands.config_cmd
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``ironclaw config`` subcommand tree.

IronClaw reads configuration from environment variables and an optional
``ironclaw.toml`` file in the current directory (or ~/.config/ironclaw/config.toml).

Commands
--------
ironclaw config show
    Print the active configuration (env vars + file values).

ironclaw config init [--path PATH]
    Write a starter ironclaw.toml to the specified path (default: ./ironclaw.toml).

ironclaw config set <key> <value>
    Update a key in ironclaw.toml (creates the file if missing).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ironclaw.cli import fmt

# ---------------------------------------------------------------------------
# Config file helpers
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATH = Path("ironclaw.toml")
_XDG_CONFIG_PATH     = Path.home() / ".config" / "ironclaw" / "config.toml"

_STARTER_TOML = """\
# ironclaw.toml — IronClaw configuration
# Docs: https://github.com/your-org/ironclaw

[server]
host = "127.0.0.1"
port = 7432

[audit]
# Path to the append-only JSONL audit log
log_path = "logs/audit.jsonl"
# HMAC secret for tamper-detection (leave empty to disable signing)
# hmac_secret = ""

[defaults]
provider = "anthropic"
model    = "claude-sonnet-4-6"
"""

_ENV_VARS = {
    "IRONCLAW_SERVER":         "Server base URL (overrides config file)",
    "IRONCLAW_AUDIT_LOG":      "Path to audit log JSONL file",
    "IRONCLAW_AUDIT_SECRET":   "HMAC secret for audit log signing",
    "IRONCLAW_DEFAULT_AGENT":  "Default agent ID for gateway routing",
    "IRONCLAW_SESSION_DB":     "Path to SQLite session store",
    "ANTHROPIC_API_KEY":       "Anthropic API key",
    "OPENAI_API_KEY":          "OpenAI API key",
}


def _find_config() -> Path | None:
    if _DEFAULT_CONFIG_PATH.exists():
        return _DEFAULT_CONFIG_PATH
    if _XDG_CONFIG_PATH.exists():
        return _XDG_CONFIG_PATH
    return None


def _read_toml(path: Path) -> dict:
    """
    Minimal TOML parser — handles only [section] headers and key = "value" /
    key = 1234 / key = true lines.  Enough for our config file.
    """
    result: dict = {}
    section: str = ""
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip()
                result.setdefault(section, {})
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if section:
                    result[section][key] = val
                else:
                    result[key] = val
    except Exception:
        pass
    return result


def _write_toml_key(path: Path, section: str, key: str, value: str) -> None:
    """
    Crude in-place writer: replace 'key = ...' inside [section] or append.
    """
    if not path.exists():
        path.write_text(_STARTER_TOML, encoding="utf-8")

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    in_section = not section
    replaced   = False
    new_lines  = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped[1:-1].strip() == section
        if in_section and stripped.startswith(key + " ="):
            new_lines.append(f'{key} = "{value}"\n')
            replaced = True
        else:
            new_lines.append(line)

    if not replaced:
        # Append to end of relevant section or end of file
        new_lines.append(f'\n[{section}]\n{key} = "{value}"\n' if section else f'{key} = "{value}"\n')

    path.write_text("".join(new_lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------

def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("config", help="Show or edit IronClaw configuration")
    s = p.add_subparsers(dest="config_cmd", metavar="<command>")
    s.required = True

    s.add_parser("show", help="Show active configuration")

    pi = s.add_parser("init", help="Write a starter ironclaw.toml")
    pi.add_argument("--path", default=str(_DEFAULT_CONFIG_PATH),
                    help=f"Where to write the file (default: {_DEFAULT_CONFIG_PATH})")

    ps = s.add_parser("set", help="Update a config key in ironclaw.toml")
    ps.add_argument("key",   help="Key in section.key form (e.g. server.port)")
    ps.add_argument("value", help="New value")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def dispatch(args: argparse.Namespace, _client: object) -> int:
    cmd = args.config_cmd
    as_json = getattr(args, "json", False)

    if cmd == "show":
        return _show(as_json)
    if cmd == "init":
        return _init(args)
    if cmd == "set":
        return _set(args)

    fmt.error(f"Unknown config command: {cmd}")
    return 1


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------

def _show(as_json: bool) -> int:
    cfg_path = _find_config()
    file_cfg = _read_toml(cfg_path) if cfg_path else {}

    env_cfg = {k: os.environ.get(k, "") for k in _ENV_VARS}

    if as_json:
        import json
        fmt.json_out({"file": str(cfg_path or "none"), "file_config": file_cfg, "env": env_cfg})
        return 0

    fmt.section("Configuration File")
    if cfg_path:
        fmt.info(f"Loaded from: {cfg_path}")
        for section, vals in file_cfg.items():
            if isinstance(vals, dict):
                print(f"\n  {fmt.bold(section)}")
                for k, v in vals.items():
                    print(f"    {fmt.colored(k, 'bcyan')}  =  {v}")
            else:
                print(f"  {fmt.colored(section, 'bcyan')}  =  {vals}")
    else:
        fmt.info(f"No config file found (looked for {_DEFAULT_CONFIG_PATH} and {_XDG_CONFIG_PATH})")
        fmt.info("Run `ironclaw config init` to create one.")

    fmt.section("Environment Variables")
    for var, desc in _ENV_VARS.items():
        val = os.environ.get(var)
        status = fmt.colored(val if val else "not set", "bgreen" if val else "red")
        print(f"  {fmt.colored(var, 'bcyan')}  {status}")
        print(f"    {fmt.dim(desc)}")

    return 0


def _init(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if path.exists():
        fmt.warn(f"{path} already exists. Use `ironclaw config set` to update it.")
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_STARTER_TOML, encoding="utf-8")
    fmt.success(f"Config written to {path}")
    return 0


def _set(args: argparse.Namespace) -> int:
    cfg_path = _find_config() or _DEFAULT_CONFIG_PATH
    key = args.key
    value = args.value

    if "." in key:
        section, _, field = key.partition(".")
    else:
        section = ""
        field   = key

    _write_toml_key(cfg_path, section, field, value)
    fmt.success(f"Set {key} = {value!r} in {cfg_path}")
    return 0

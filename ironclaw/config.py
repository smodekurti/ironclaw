"""
ironclaw.config
~~~~~~~~~~~~~~~
Configuration management.

IronClaw reads settings from (in priority order):
  1. Explicit kwargs to IronClawConfig(...)
  2. Environment variables prefixed with ``IRONCLAW_``
  3. A TOML config file (default: ``~/.ironclaw/config.toml``)
  4. Hardcoded defaults below

Usage
-----
::

    from ironclaw.config import IronClawConfig
    cfg = IronClawConfig.load()
    print(cfg.default_model)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]


_DEFAULT_CONFIG_PATH = Path.home() / ".ironclaw" / "config.toml"


@dataclass
class IronClawConfig:
    # LLM defaults
    default_provider: str = "anthropic"
    default_model: str = "claude-sonnet-4-6"
    default_temperature: float = 0.7
    default_max_tokens: int = 4096

    # API keys (prefer env vars — these are fallbacks)
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Security
    guard_block_threshold: float = 0.75
    guard_warn_threshold: float = 0.45
    guard_max_length: int = 32_000
    audit_log_path: str = ""
    audit_hmac_secret: str = ""

    # Sandbox
    sandbox_timeout: float = 30.0
    sandbox_max_output_chars: int = 64_000

    # Memory
    memory_db_path: str = ""   # empty → in-memory
    max_conversation_messages: int = 200

    # Filesystem tool
    allowed_roots: list[str] = field(default_factory=list)

    # Rate limiting
    rate_limit_calls: int = 60
    rate_limit_window: float = 60.0

    # CLI
    log_level: str = "INFO"

    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path | None = None) -> "IronClawConfig":
        """
        Load config from file + environment, returning an IronClawConfig.
        """
        file_data: dict[str, Any] = {}

        config_path = Path(path) if path else _DEFAULT_CONFIG_PATH
        if config_path.exists() and tomllib:
            with open(config_path, "rb") as f:
                file_data = tomllib.load(f).get("ironclaw", {})

        # Merge env overrides (IRONCLAW_DEFAULT_MODEL → default_model)
        env_data: dict[str, Any] = {}
        for key in cls.__dataclass_fields__:
            env_key = f"IRONCLAW_{key.upper()}"
            val = os.environ.get(env_key)
            if val is not None:
                # Simple type coercion
                field_type = cls.__dataclass_fields__[key].type
                try:
                    if "float" in str(field_type):
                        env_data[key] = float(val)
                    elif "int" in str(field_type):
                        env_data[key] = int(val)
                    elif "bool" in str(field_type):
                        env_data[key] = val.lower() in ("1", "true", "yes")
                    else:
                        env_data[key] = val
                except (ValueError, TypeError):
                    env_data[key] = val

        # Also pick up standard API key env vars
        if not env_data.get("anthropic_api_key"):
            env_data["anthropic_api_key"] = os.environ.get("ANTHROPIC_API_KEY", "")
        if not env_data.get("openai_api_key"):
            env_data["openai_api_key"] = os.environ.get("OPENAI_API_KEY", "")

        merged = {**file_data, **env_data}
        return cls(**{k: v for k, v in merged.items() if k in cls.__dataclass_fields__})

    def save(self, path: str | Path | None = None) -> None:
        """Persist config to a TOML file (requires ``tomli-w``)."""
        try:
            import tomli_w
        except ImportError:
            raise ImportError("pip install tomli-w to save config files")

        save_path = Path(path) if path else _DEFAULT_CONFIG_PATH
        save_path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: getattr(self, k) for k in self.__dataclass_fields__}
        with open(save_path, "wb") as f:
            tomli_w.dump({"ironclaw": data}, f)

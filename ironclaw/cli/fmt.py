"""
ironclaw.cli.fmt
~~~~~~~~~~~~~~~~
ANSI-colored terminal output helpers for the IronClaw CLI.

Uses only stdlib — no `rich`, no `colorama`.

Public API
----------
- ``cprint(text, color, bold, file)`` — print with ANSI color
- ``success(msg)``  / ``error(msg)``  / ``warn(msg)``  / ``info(msg)``
- ``table(rows, headers, col_widths)`` — fixed-width ASCII table
- ``key_value(data, indent)`` — aligned key: value block
- ``json_out(obj)`` — pretty-printed JSON (bypasses color)
- ``dim(text)`` — wrap in dim ANSI code
- ``bold(text)`` — wrap in bold ANSI code
- ``fmt_status(running)`` — green ● or red ○
- ``truncate(s, n)`` — truncate string to n chars with ellipsis
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Detect color support
# ---------------------------------------------------------------------------

def _supports_color() -> bool:
    """Return True if the terminal likely supports ANSI escape codes."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if not hasattr(sys.stdout, "isatty"):
        return False
    return sys.stdout.isatty()


_COLOR = _supports_color()

# ANSI codes
_RESET   = "\033[0m"
_BOLD    = "\033[1m"
_DIM     = "\033[2m"

_COLORS = {
    "black":   "\033[30m",
    "red":     "\033[31m",
    "green":   "\033[32m",
    "yellow":  "\033[33m",
    "blue":    "\033[34m",
    "magenta": "\033[35m",
    "cyan":    "\033[36m",
    "white":   "\033[37m",
    # bright variants
    "bred":    "\033[91m",
    "bgreen":  "\033[92m",
    "byellow": "\033[93m",
    "bblue":   "\033[94m",
    "bmagenta":"\033[95m",
    "bcyan":   "\033[96m",
    "bwhite":  "\033[97m",
}


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _ansi(text: str, color: str | None = None, is_bold: bool = False, is_dim: bool = False) -> str:
    """Wrap *text* in ANSI escape codes (no-op if colors disabled)."""
    if not _COLOR:
        return text
    prefix = ""
    if is_bold:
        prefix += _BOLD
    if is_dim:
        prefix += _DIM
    if color:
        prefix += _COLORS.get(color, "")
    if not prefix:
        return text
    return f"{prefix}{text}{_RESET}"


def bold(text: str) -> str:
    return _ansi(text, is_bold=True)


def dim(text: str) -> str:
    return _ansi(text, is_dim=True)


def colored(text: str, color: str) -> str:
    return _ansi(text, color=color)


# ---------------------------------------------------------------------------
# Convenience print functions
# ---------------------------------------------------------------------------

def cprint(
    text: str,
    color: str | None = None,
    is_bold: bool = False,
    file: Any = None,
) -> None:
    print(_ansi(text, color=color, is_bold=is_bold), file=file or sys.stdout)


def success(msg: str) -> None:
    print(_ansi("✓ ", "bgreen", is_bold=True) + msg)


def error(msg: str) -> None:
    print(_ansi("✗ Error: ", "bred", is_bold=True) + msg, file=sys.stderr)


def warn(msg: str) -> None:
    print(_ansi("⚠ ", "byellow", is_bold=True) + msg, file=sys.stderr)


def info(msg: str) -> None:
    print(_ansi("• ", "bcyan") + msg)


def section(title: str) -> None:
    """Print a bold section header with a rule below it."""
    line = "─" * min(len(title) + 4, 72)
    print()
    print(bold(title))
    print(dim(line))


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

def json_out(obj: Any) -> None:
    """Pretty-print *obj* as JSON (no ANSI codes)."""
    print(json.dumps(obj, indent=2, default=str))


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------

def truncate(s: str, n: int) -> str:
    s = str(s)
    if len(s) <= n:
        return s
    return s[: max(n - 1, 0)] + "…"


def table(
    rows: list[dict | list],
    headers: list[str],
    col_widths: list[int] | None = None,
    *,
    max_col_width: int = 40,
) -> None:
    """
    Print a fixed-width ASCII table.

    Parameters
    ----------
    rows :
        List of dicts (keys = headers) or lists (positional).
    headers :
        Column header names. For dict rows these are also the keys.
    col_widths :
        Fixed widths per column. If None, auto-sized from data + header.
    max_col_width :
        Cap for auto-computed widths.
    """
    if not rows:
        print(dim("  (no entries)"))
        return

    n = len(headers)

    # Normalise rows to lists
    norm: list[list[str]] = []
    for row in rows:
        if isinstance(row, dict):
            norm.append([str(row.get(h, "")) for h in headers])
        else:
            norm.append([str(c) for c in list(row)[:n]])

    # Compute widths
    if col_widths is None:
        widths = [len(h) for h in headers]
        for row in norm:
            for i, cell in enumerate(row):
                widths[i] = min(max(widths[i], len(cell)), max_col_width)
    else:
        widths = list(col_widths)

    # Header row
    sep = "  "
    header_parts = [
        bold(_ansi(truncate(h, widths[i]).ljust(widths[i]), "bwhite"))
        for i, h in enumerate(headers)
    ]
    print(sep.join(header_parts))

    # Divider
    divider = dim(sep.join("─" * w for w in widths))
    print(divider)

    # Data rows
    for row in norm:
        cells = [truncate(cell, widths[i]).ljust(widths[i]) for i, cell in enumerate(row)]
        print(sep.join(cells))


# ---------------------------------------------------------------------------
# Key-value block
# ---------------------------------------------------------------------------

def key_value(data: dict, indent: int = 0, key_width: int | None = None) -> None:
    """
    Print a dict as aligned ``key: value`` lines.

    Example::

        agent_id  : my-agent
        name      : My Agent
        provider  : anthropic
    """
    if not data:
        return
    pad = " " * indent
    kw = key_width or max(len(str(k)) for k in data)
    for k, v in data.items():
        key_str = _ansi(str(k).ljust(kw), "bcyan")
        if isinstance(v, (dict, list)):
            v_str = json.dumps(v, default=str)
        else:
            v_str = str(v)
        print(f"{pad}{key_str}  {v_str}")


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------

def fmt_status(running: bool) -> str:
    """Return a colored running/stopped indicator."""
    if running:
        return _ansi("● running", "bgreen")
    return _ansi("○ stopped", "red")


def fmt_bool(value: bool) -> str:
    if value:
        return _ansi("yes", "bgreen")
    return _ansi("no", "red")


def fmt_ts(ts: str | None) -> str:
    """Return a dimmed timestamp string."""
    if not ts:
        return dim("—")
    return dim(str(ts)[:19].replace("T", " "))

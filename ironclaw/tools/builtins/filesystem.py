"""
ironclaw.tools.builtins.filesystem
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Safe file-system tools.

Security constraints
--------------------
- All paths are resolved to absolute paths and checked against an *allowed
  roots* list.  Any attempt to read/write outside allowed roots raises
  PermissionError.
- Symlinks that point outside the allowed root are rejected.
- File write is limited to ``max_write_bytes`` (default 1 MB).
- No execution — these tools read and write text only.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ironclaw.tools.registry import ToolRegistry

_MAX_READ_BYTES = 512 * 1024    # 512 KB
_MAX_WRITE_BYTES = 1024 * 1024  # 1 MB
_ALLOWED_ROOTS: list[Path] = []  # populated by register_filesystem_tools


def _check_path(p: str) -> Path:
    """Resolve and validate that *p* falls inside an allowed root."""
    resolved = Path(p).resolve()
    # Reject symlinks pointing outside allowed roots
    if resolved.is_symlink():
        real = resolved.readlink().resolve()
        _check_root(real)
    _check_root(resolved)
    return resolved


def _check_root(resolved: Path) -> None:
    if not _ALLOWED_ROOTS:
        return  # no restriction configured
    for root in _ALLOWED_ROOTS:
        try:
            resolved.relative_to(root)
            return  # inside this root — allowed
        except ValueError:
            continue
    raise PermissionError(
        f"Path '{resolved}' is outside allowed roots: {[str(r) for r in _ALLOWED_ROOTS]}"
    )


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def _read_file(path: str) -> str:
    p = _check_path(path)
    if not p.exists():
        raise FileNotFoundError(f"No such file: {path}")
    if p.stat().st_size > _MAX_READ_BYTES:
        raise ValueError(
            f"File too large ({p.stat().st_size} bytes > {_MAX_READ_BYTES} limit)"
        )
    return p.read_text(encoding="utf-8", errors="replace")


async def _write_file(path: str, content: str, overwrite: bool = False) -> str:
    p = _check_path(path)
    if p.exists() and not overwrite:
        raise FileExistsError(f"File already exists: {path}. Set overwrite=true to replace.")
    if len(content.encode("utf-8")) > _MAX_WRITE_BYTES:
        raise ValueError(f"Content exceeds max write size of {_MAX_WRITE_BYTES} bytes")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Written {len(content)} chars to {path}"


async def _list_directory(path: str) -> list[dict[str, Any]]:
    p = _check_path(path)
    if not p.is_dir():
        raise NotADirectoryError(f"Not a directory: {path}")
    entries = []
    for child in sorted(p.iterdir()):
        entries.append(
            {
                "name": child.name,
                "type": "dir" if child.is_dir() else "file",
                "size": child.stat().st_size if child.is_file() else None,
            }
        )
    return entries


async def _delete_file(path: str) -> str:
    p = _check_path(path)
    if not p.exists():
        raise FileNotFoundError(f"No such file: {path}")
    if p.is_dir():
        raise IsADirectoryError(f"Use a dedicated tool to delete directories: {path}")
    p.unlink()
    return f"Deleted {path}"


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def register_filesystem_tools(
    registry: ToolRegistry,
    allowed_roots: list[str] | None = None,
) -> None:
    """
    Register filesystem tools into *registry*.

    Parameters
    ----------
    allowed_roots : list[str] | None
        Directories agents are permitted to access.  ``None`` → no restriction
        (not recommended for production).
    """
    global _ALLOWED_ROOTS
    if allowed_roots is not None:
        _ALLOWED_ROOTS = [Path(r).resolve() for r in allowed_roots]

    registry.register(
        __import__("ironclaw.tools.registry", fromlist=["ToolSpec"]).ToolSpec(
            name="file:read",
            description="Read a text file from the filesystem.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or relative file path"},
                },
                "required": ["path"],
            },
            fn=_read_file,
            requires="file:read",
        )
    )

    registry.register(
        __import__("ironclaw.tools.registry", fromlist=["ToolSpec"]).ToolSpec(
            name="file:write",
            description="Write or overwrite a text file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "overwrite": {"type": "boolean", "default": False},
                },
                "required": ["path", "content"],
            },
            fn=_write_file,
            requires="file:write",
        )
    )

    registry.register(
        __import__("ironclaw.tools.registry", fromlist=["ToolSpec"]).ToolSpec(
            name="file:list",
            description="List the contents of a directory.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
            fn=_list_directory,
            requires="file:read",
        )
    )

    registry.register(
        __import__("ironclaw.tools.registry", fromlist=["ToolSpec"]).ToolSpec(
            name="file:delete",
            description="Delete a file (not a directory).",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
            fn=_delete_file,
            requires="file:write",
        )
    )

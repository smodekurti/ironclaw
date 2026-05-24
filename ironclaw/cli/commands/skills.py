"""
ironclaw.cli.commands.skills
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``ironclaw skills`` subcommand tree.

Commands
--------
ironclaw skills list [--dir PATH]
    Discover and list all skills in the skills directory.

ironclaw skills show <skill-name> [--dir PATH]
    Print the full SKILL.md for a skill.

ironclaw skills install <path-or-url>
    Copy a skill directory into the user skills folder (~/.ironclaw/skills/).

ironclaw skills validate <path>
    Validate that a skill directory meets the agentskills.io spec.

ironclaw skills new <name>
    Scaffold a new skill directory with a starter SKILL.md.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from ironclaw.cli import fmt

_DEFAULT_SKILL_DIR = Path.home() / ".ironclaw" / "skills"
_BUILTIN_DIR = Path(__file__).parent.parent.parent / "skills" / "builtin"


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------

def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("skills", help="Manage agent skills (agentskills.io format)")
    s = p.add_subparsers(dest="skills_cmd", metavar="<command>")
    s.required = True

    # list
    pl = s.add_parser("list", help="List available skills")
    pl.add_argument("--dir", default=None, help="Skills directory (default: ~/.ironclaw/skills + built-ins)")

    # show
    psh = s.add_parser("show", help="Print the full SKILL.md for a skill")
    psh.add_argument("name", help="Skill name")
    psh.add_argument("--dir", default=None)

    # install
    pi = s.add_parser("install", help="Install a skill from a local path")
    pi.add_argument("source", help="Path to a skill directory containing SKILL.md")
    pi.add_argument("--into", default=str(_DEFAULT_SKILL_DIR),
                    help=f"Target skills directory (default: {_DEFAULT_SKILL_DIR})")

    # validate
    pv = s.add_parser("validate", help="Validate a skill directory against the spec")
    pv.add_argument("path", help="Path to skill directory")

    # new
    pn = s.add_parser("new", help="Scaffold a new skill")
    pn.add_argument("name", help="Skill name (lowercase, hyphens only)")
    pn.add_argument("--out", default=".", help="Parent directory for the new skill folder (default: .)")


# ---------------------------------------------------------------------------
# Dispatch (no server required)
# ---------------------------------------------------------------------------

def dispatch(args: argparse.Namespace, _client: object) -> int:
    cmd = args.skills_cmd
    as_json = getattr(args, "json", False)

    if cmd == "list":
        return _list(args, as_json)
    if cmd == "show":
        return _show(args, as_json)
    if cmd == "install":
        return _install(args)
    if cmd == "validate":
        return _validate(args)
    if cmd == "new":
        return _new(args)

    fmt.error(f"Unknown skills command: {cmd}")
    return 1


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------

def _get_registry(skill_dir: str | None) -> "SkillRegistry":
    from ironclaw.skills.registry import SkillRegistry
    reg = SkillRegistry()
    reg.add_directory(_BUILTIN_DIR)
    user_dir = Path(skill_dir) if skill_dir else _DEFAULT_SKILL_DIR
    reg.add_directory(user_dir)
    return reg


def _list(args: argparse.Namespace, as_json: bool) -> int:
    reg = _get_registry(getattr(args, "dir", None))

    if as_json:
        fmt.json_out(reg.summaries())
        return 0

    if not len(reg):
        fmt.info("No skills found. Install built-in skills with: ironclaw skills install --builtin")
        return 0

    fmt.section(f"Available Skills ({len(reg)})")
    print()
    for name in reg.names:
        m = reg.get(name)
        if m:
            path_info = fmt.dim(f"  {m.path}")
            print(f"  {fmt.bold(fmt.colored(name, 'bcyan')):<40} {m.description[:72]}")
            print(f"  {path_info}")
            print()
    return 0


def _show(args: argparse.Namespace, as_json: bool) -> int:
    reg = _get_registry(getattr(args, "dir", None))
    m = reg.get(args.name)
    if not m:
        fmt.error(f"Skill '{args.name}' not found")
        return 1

    if as_json:
        fmt.json_out({
            "name": m.name,
            "description": m.description,
            "body": m.body,
            "license": m.license,
            "compatibility": m.compatibility,
            "allowed_tools": m.allowed_tools,
            "metadata": m.metadata,
            "path": str(m.path),
        })
        return 0

    fmt.section(f"Skill: {m.name}")
    fmt.key_value({
        "description":   m.description,
        "license":       m.license or "—",
        "compatibility": m.compatibility or "—",
        "allowed_tools": " ".join(m.allowed_tools) or "—",
        "path":          str(m.path),
    }, indent=2)

    if m.metadata:
        print()
        fmt.key_value(m.metadata, indent=4)

    if m.body:
        print()
        fmt.section("Instructions")
        print(m.body)

    return 0


def _install(args: argparse.Namespace) -> int:
    source = Path(args.source)
    if not source.exists():
        fmt.error(f"Source path not found: {source}")
        return 1

    skill_md = source / "SKILL.md"
    if not skill_md.exists():
        fmt.error(f"No SKILL.md found in {source}")
        return 1

    # Validate first
    from ironclaw.skills.manifest import SkillManifest
    try:
        manifest = SkillManifest.from_file(skill_md)
    except Exception as e:
        fmt.error(f"Skill validation failed: {e}")
        return 1

    target = Path(args.into) / manifest.name
    if target.exists():
        fmt.warn(f"Skill '{manifest.name}' already installed at {target}")
        try:
            overwrite = input("  Overwrite? (y/N): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return 1
        if not overwrite.startswith("y"):
            fmt.info("Aborted.")
            return 0
        shutil.rmtree(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    fmt.success(f"Installed skill '{manifest.name}' → {target}")
    return 0


def _validate(args: argparse.Namespace) -> int:
    from ironclaw.skills.manifest import SkillManifest

    path = Path(args.path)
    skill_md = path / "SKILL.md"
    if not skill_md.exists():
        fmt.error(f"No SKILL.md in {path}")
        return 1

    errors = []
    try:
        manifest = SkillManifest.from_file(skill_md)
    except Exception as e:
        errors.append(str(e))

    if errors:
        fmt.error("Validation failed:")
        for err in errors:
            print(f"    • {err}")
        return 1

    # Extra checks
    if manifest.name != path.name:
        fmt.warn(f"Directory name '{path.name}' doesn't match skill name '{manifest.name}' (spec requires they match)")

    fmt.success(f"Skill '{manifest.name}' is valid")
    fmt.key_value({
        "name":          manifest.name,
        "description":   manifest.description[:60] + ("…" if len(manifest.description) > 60 else ""),
        "has_scripts":   "yes" if manifest.script_dir().exists() else "no",
        "has_references":"yes" if manifest.references_dir().exists() else "no",
        "has_assets":    "yes" if manifest.assets_dir().exists() else "no",
    }, indent=2)
    return 0


def _new(args: argparse.Namespace) -> int:
    from ironclaw.skills.manifest import _NAME_RE, _validate as _v

    name = args.name.strip().lower()
    if not _NAME_RE.match(name):
        fmt.error(f"Invalid skill name '{name}' — use lowercase letters, numbers, and hyphens only")
        return 1

    out_dir = Path(args.out) / name
    if out_dir.exists():
        fmt.error(f"Directory already exists: {out_dir}")
        return 1

    out_dir.mkdir(parents=True)
    (out_dir / "scripts").mkdir()
    (out_dir / "references").mkdir()
    (out_dir / "assets").mkdir()

    skill_md = out_dir / "SKILL.md"
    skill_md.write_text(
        f"---\n"
        f"name: {name}\n"
        f"description: Describe what this skill does and when to use it.\n"
        f"license: MIT\n"
        f"metadata:\n"
        f"  author: your-name\n"
        f"  version: \"1.0\"\n"
        f"---\n\n"
        f"# {name}\n\n"
        f"## Overview\n\n"
        f"Describe the skill here.\n\n"
        f"## Instructions\n\n"
        f"Step-by-step instructions for the agent:\n\n"
        f"1. First step\n"
        f"2. Second step\n"
        f"3. Third step\n\n"
        f"## Examples\n\n"
        f"**Input:** ...\n"
        f"**Output:** ...\n",
        encoding="utf-8",
    )

    fmt.success(f"Scaffolded skill '{name}' at {out_dir}")
    fmt.key_value({
        "SKILL.md":    str(skill_md),
        "scripts/":   str(out_dir / "scripts"),
        "references/": str(out_dir / "references"),
        "assets/":    str(out_dir / "assets"),
    }, indent=2)
    fmt.info("Edit SKILL.md, then validate: ironclaw skills validate " + str(out_dir))
    return 0


# Avoid circular import at module level
SkillRegistry = None
try:
    from ironclaw.skills.registry import SkillRegistry  # type: ignore[assignment]
except Exception:
    pass

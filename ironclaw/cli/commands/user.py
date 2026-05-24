"""
ironclaw.cli.commands.user
~~~~~~~~~~~~~~~~~~~~~~~~~~
``ironclaw user`` subcommand tree — manage the global user profile.

The user profile tells every agent who you are and how to behave with you.
It is stored at ``~/.ironclaw/user_profile.json`` and loaded automatically
by all agents at startup.

Commands
--------
ironclaw user show
    Print the current user profile.

ironclaw user set --name "Alex" --role "Engineer" ...
    Set one or more profile fields.

ironclaw user do "Always cite your sources"
    Add a 'must always do' rule.

ironclaw user dont "Never suggest rewriting from scratch"
    Add a 'must never do' rule.

ironclaw user remove-do "..."
    Remove a specific 'do' rule.

ironclaw user remove-dont "..."
    Remove a specific 'dont' rule.

ironclaw user pref tone=direct verbosity=low
    Set communication preferences as key=value pairs.

ironclaw user clear
    Wipe the entire profile.

ironclaw user edit
    Open the profile JSON in $EDITOR.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

from ironclaw.cli import fmt


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------

def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("user", help="Manage your user profile (identity, do's & don'ts)")
    s = p.add_subparsers(dest="user_cmd", metavar="<command>")
    s.required = True

    # show
    s.add_parser("show", help="Print the current user profile")

    # set
    ps = s.add_parser("set", help="Set one or more profile fields")
    ps.add_argument("--name",         default=None, help="Your name")
    ps.add_argument("--email",        default=None, help="Your email address")
    ps.add_argument("--role",         default=None, help="Your job title or role")
    ps.add_argument("--organization", default=None, help="Your company or team")
    ps.add_argument("--timezone",     default=None, help="Your timezone, e.g. America/New_York")
    ps.add_argument("--language",     default=None, help="Primary language for responses")
    ps.add_argument("--context",      default=None, help="Free-form background about you")

    # do
    pdo = s.add_parser("do", help="Add a 'must always do' rule")
    pdo.add_argument("rule", help="Rule text, e.g. 'Always cite your sources'")

    # dont
    pdt = s.add_parser("dont", help="Add a 'must never do' rule")
    pdt.add_argument("rule", help="Rule text, e.g. 'Never use jargon'")

    # remove-do
    prd = s.add_parser("remove-do", help="Remove a specific 'do' rule")
    prd.add_argument("rule", help="Exact rule text to remove")

    # remove-dont
    prdt = s.add_parser("remove-dont", help="Remove a specific 'dont' rule")
    prdt.add_argument("rule", help="Exact rule text to remove")

    # pref  (key=value pairs)
    pp = s.add_parser("pref", help="Set communication preferences (key=value)")
    pp.add_argument(
        "pairs", nargs="+", metavar="KEY=VALUE",
        help="Preferences: tone=direct verbosity=low format=markdown expertise_level=expert",
    )

    # goal
    pg = s.add_parser("goal", help="Add a goal")
    pg.add_argument("goal", help="Goal text, e.g. 'Launch MVP by Q3'")

    # clear
    s.add_parser("clear", help="Wipe the entire user profile")

    # edit
    s.add_parser("edit", help="Open the profile JSON in $EDITOR")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def dispatch(args: argparse.Namespace, _client) -> int:
    cmd = args.user_cmd
    as_json = getattr(args, "json", False)

    if cmd == "show":
        return _show(as_json)
    if cmd == "set":
        return _set(args)
    if cmd == "do":
        return _add_do(args.rule)
    if cmd == "dont":
        return _add_dont(args.rule)
    if cmd == "remove-do":
        return _remove_do(args.rule)
    if cmd == "remove-dont":
        return _remove_dont(args.rule)
    if cmd == "pref":
        return _set_prefs(args.pairs)
    if cmd == "goal":
        return _add_goal(args.goal)
    if cmd == "clear":
        return _clear()
    if cmd == "edit":
        return _edit()

    fmt.error(f"Unknown user command: {cmd}")
    return 1


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------

def _store():
    from ironclaw.user.store import UserProfileStore
    return UserProfileStore()


def _show(as_json: bool) -> int:
    store = _store()
    profile = store.load()

    if as_json:
        print(profile.to_json())
        return 0

    if profile.is_empty():
        fmt.info(
            "No user profile set. Use `ironclaw user set --name ...` to get started.\n"
            f"  Profile will be stored at: {store.path}"
        )
        return 0

    fmt.section("User Profile")
    print(str(profile))
    print()
    fmt.dim(f"  Stored at: {store.path}")
    return 0


def _set(args: argparse.Namespace) -> int:
    fields = {}
    for key in ("name", "email", "role", "organization", "timezone", "language", "context"):
        val = getattr(args, key, None)
        if val is not None:
            fields[key] = val

    if not fields:
        fmt.error("No fields provided. Use --name, --role, --email, etc.")
        return 1

    profile = _store().update(**fields)
    fmt.success("User profile updated")
    for k, v in fields.items():
        fmt.dim(f"  {k}: {v}")
    return 0


def _add_do(rule: str) -> int:
    _store().add_do(rule)
    fmt.success(f"Added rule: always do → {rule!r}")
    return 0


def _add_dont(rule: str) -> int:
    _store().add_dont(rule)
    fmt.success(f"Added rule: never do → {rule!r}")
    return 0


def _remove_do(rule: str) -> int:
    profile = _store().remove_do(rule)
    fmt.success(f"Removed 'do' rule: {rule!r}")
    return 0


def _remove_dont(rule: str) -> int:
    profile = _store().remove_dont(rule)
    fmt.success(f"Removed 'dont' rule: {rule!r}")
    return 0


def _set_prefs(pairs: list[str]) -> int:
    prefs: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            fmt.error(f"Invalid preference format: {pair!r}  (expected KEY=VALUE)")
            return 1
        k, _, v = pair.partition("=")
        prefs[k.strip()] = v.strip()

    _store().update(preferences=prefs)
    fmt.success("Preferences updated")
    for k, v in prefs.items():
        fmt.dim(f"  {k}: {v}")
    return 0


def _add_goal(goal: str) -> int:
    store = _store()
    profile = store.load()
    if goal not in profile.goals:
        profile.goals.append(goal)
        store.save(profile)
    fmt.success(f"Added goal: {goal!r}")
    return 0


def _clear() -> int:
    store = _store()
    if not store.exists():
        fmt.info("No profile to clear.")
        return 0

    try:
        answer = input(fmt.colored("Clear entire user profile? [y/N] ", "byellow"))
    except (KeyboardInterrupt, EOFError):
        print()
        return 0

    if answer.strip().lower() in ("y", "yes"):
        store.clear()
        fmt.success("User profile cleared.")
    else:
        fmt.info("Cancelled.")
    return 0


def _edit() -> int:
    store = _store()
    profile = store.load()
    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", "nano"))

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(profile.to_json())
        tmp = fh.name

    try:
        subprocess.run([editor, tmp], check=True)
        with open(tmp, encoding="utf-8") as fh:
            data = json.load(fh)
        from ironclaw.user.profile import UserProfile
        updated = UserProfile.from_dict(data)
        store.save(updated)
        fmt.success("User profile saved.")
    except subprocess.CalledProcessError:
        fmt.error(f"Editor exited with an error. No changes saved.")
        return 1
    except json.JSONDecodeError as exc:
        fmt.error(f"Invalid JSON: {exc}. No changes saved.")
        return 1
    finally:
        os.unlink(tmp)

    return 0

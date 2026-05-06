from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import click


def _print_hook_json(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload))
    sys.stdout.write("\n")


@click.group("hook")
def hook_group() -> None:
    """Hooks for Claude Code (read JSON from stdin, write JSON to stdout)."""


@hook_group.command("pre-grep-glob")
def hook_pre_grep_glob() -> None:
    """PreToolUse: remind to prefer codeidx for structural search."""
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return
    name = data.get("tool_name")
    if name not in ("Grep", "Glob"):
        return
    _print_hook_json(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "additionalContext": (
                    "Prefer the codeidx SQLite index (MCP: read_query / symbols_fts / edges) "
                    "for symbols, callers, paths, and FTS before large Grep/Glob scans—it is "
                    "usually faster and uses fewer tokens than raw repository grep."
                ),
            }
        }
    )


@hook_group.command("post-cs-edit")
def hook_post_cs_edit() -> None:
    """PostToolUse: remind to update knowledge notes after C# edits."""
    try:
        json.load(sys.stdin)
    except json.JSONDecodeError:
        pass
    _print_hook_json(
        {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": (
                    "C# source was just changed. Add **knowledge** in the repo’s **markdown symbol "
                    "notes** (under `.codeidx/notes/`), **not** by editing `.cs` again for prose. "
                    "Pick the main type/method you touched (`QualifiedName`). "
                    "Use the **codeidx MCP tools** `get_or_create_note` (if the note is missing) "
                    "and `append_note` — prose goes under the `## Notes` heading only. "
                    "Use `sync_note_structure` when you need the auto-generated sections refreshed "
                    "from the index."
                ),
            }
        }
    )


@hook_group.command("session-start")
@click.option(
    "--db",
    "db_path",
    type=click.Path(path_type=Path),
    required=True,
    help="Path to codeidx SQLite database",
)
@click.option(
    "--repo",
    "repo_root",
    type=click.Path(path_type=Path, file_okay=False),
    required=True,
    help="Git repository root to compare against",
)
def hook_session_start(db_path: Path, repo_root: Path) -> None:
    """SessionStart: warn if the index is older than the latest git commit."""
    try:
        json.load(sys.stdin)
    except json.JSONDecodeError:
        pass

    db = db_path.resolve()
    repo = repo_root.resolve()

    if not db.is_file():
        _print_hook_json(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": (
                        f"codeidx: no database at {db} (expected <repo>/.codeidx/db/codeidx.db). "
                        f"Build it with: python -m codeidx index {repo}"
                    ),
                }
            }
        )
        return

    try:
        r = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%ct"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except OSError:
        return
    if r.returncode != 0 or not r.stdout.strip():
        return
    try:
        commit_ts = int(r.stdout.strip())
    except ValueError:
        return

    db_mtime = int(db.stat().st_mtime)
    if db_mtime < commit_ts:
        _print_hook_json(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": (
                        "codeidx: the SQLite index may be older than the latest git commit "
                        f"under {repo}. Re-index with: python -m codeidx index --force . "
                        "(from the indexed repo root, or pass the root path)."
                    ),
                }
            }
        )

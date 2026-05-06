from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codeidx.agents.json_util import read_json_file, write_json_file

CODEIDX_CLAUDE_MD_BEGIN = "<!-- codeidx init-agents: start -->"
CODEIDX_CLAUDE_MD_END = "<!-- codeidx init-agents: end -->"

# Substrings for idempotency (match `codeidx`, `codeidx.exe`, or `python -m codeidx`).
MARK_PRE = "hook pre-grep-glob"
MARK_POST = "hook post-cs-edit"
MARK_SESSION = "hook session-start"

# Shown in Claude for PostToolUse while the hook runs (command output has full prose).
POST_CS_STATUS_MESSAGE = (
    "codeidx: after C# saves, add prose to `.codeidx/notes/*.md` "
    "(`notes get-or-create` then `notes append` under `## Notes` — not in `.cs` files)"
)


@dataclass
class ClaudeInitResult:
    settings_path: Path
    claude_md_path: Path | None
    messages: list[str]


def _command_line(*parts: str) -> str:
    return subprocess.list2cmdline(list(parts))


def _hook_argv(action: str, *tail: str) -> list[str]:
    """Prefer the `codeidx` executable (e.g. pipx) so hooks match `codeidx --help`, not system `python3 -m codeidx`."""
    shim = shutil.which("codeidx")
    if shim:
        return [shim, "hook", action, *tail]
    return [sys.executable, "-m", "codeidx", "hook", action, *tail]


def _hook_command_contains(groups: list[Any], marker: str) -> bool:
    for group in groups:
        if not isinstance(group, dict):
            continue
        for h in group.get("hooks", []) or []:
            if not isinstance(h, dict):
                continue
            cmd = h.get("command")
            if isinstance(cmd, str) and marker in cmd:
                return True
    return False


def _append_hook_group(hooks_list: list[Any], group: dict[str, Any]) -> None:
    hooks_list.append(group)


def build_claude_hook_defs(db_path: Path, repo_root: Path) -> dict[str, list[dict[str, Any]]]:
    session_cmd = _command_line(
        *_hook_argv(
            "session-start",
            "--db",
            str(db_path.resolve()),
            "--repo",
            str(repo_root.resolve()),
        )
    )
    pre_cmd = _command_line(*_hook_argv("pre-grep-glob"))
    post_cmd = _command_line(*_hook_argv("post-cs-edit"))

    return {
        "PreToolUse": [
            {
                "matcher": "Grep|Glob",
                "hooks": [
                    {
                        "type": "command",
                        "command": pre_cmd,
                        "statusMessage": "codeidx: prefer SQLite FTS / symbols over raw Grep/Glob when searching code structure",
                    }
                ],
            }
        ],
        "PostToolUse": [
            {
                "matcher": "Edit|Write",
                "if": "Edit(*.cs)|Write(*.cs)",
                "hooks": [
                    {
                        "type": "command",
                        "command": post_cmd,
                        "statusMessage": POST_CS_STATUS_MESSAGE,
                    }
                ],
            }
        ],
        "SessionStart": [
            {
                "matcher": "startup|resume|clear|compact",
                "hooks": [
                    {
                        "type": "command",
                        "command": session_cmd,
                    }
                ],
            }
        ],
    }


def _sync_codeidx_hook_commands(
    hooks: dict[str, Any],
    db_path: Path,
    repo_root: Path,
) -> list[str]:
    """Keep embedded commands and PostToolUse status in sync with this run's db/repo and PATH."""
    messages: list[str] = []
    pre = _command_line(*_hook_argv("pre-grep-glob"))
    post = _command_line(*_hook_argv("post-cs-edit"))
    session = _command_line(
        *_hook_argv(
            "session-start",
            "--db",
            str(db_path.resolve()),
            "--repo",
            str(repo_root.resolve()),
        )
    )
    for event, marker, new_cmd, status_msg in (
        ("PreToolUse", MARK_PRE, pre, None),
        ("PostToolUse", MARK_POST, post, POST_CS_STATUS_MESSAGE),
        ("SessionStart", MARK_SESSION, session, None),
    ):
        for group in hooks.get(event, []):
            if not isinstance(group, dict):
                continue
            for h in group.get("hooks", []) or []:
                if not isinstance(h, dict):
                    continue
                cmd = h.get("command")
                if not isinstance(cmd, str) or marker not in cmd:
                    continue
                if cmd != new_cmd:
                    h["command"] = new_cmd
                    if "-m codeidx hook" in cmd:
                        messages.append(f"Refreshed hook ({event}) to use `codeidx` on PATH")
                    else:
                        messages.append(f"Updated codeidx hook command ({event})")
                if status_msg is not None and h.get("statusMessage") != status_msg:
                    h["statusMessage"] = status_msg
                    messages.append(f"Updated codeidx hook statusMessage ({event})")
    return messages


def _codeidx_claude_md_section(db_path: Path, repo_root: Path) -> str:
    """Facts for Claude Code project context (hooks are not files named pre-grep-glob)."""
    db_s = str(db_path.resolve())
    repo_s = str(repo_root.resolve())
    return f"""## codeidx (project)

Hooks are configured in **`.claude/settings.local.json`**. They invoke **`codeidx hook …`** subcommands — there is no script file named `pre-grep-glob` on disk.

- **`codeidx hook pre-grep-glob`** — **PreToolUse** when the tool is **Grep** or **Glob**. Injects a reminder to use the codeidx SQLite index (MCP / `read_query`, FTS) for structure before huge repo scans.
- **`codeidx hook post-cs-edit`** — **PostToolUse** after **Edit/Write** of **`*.cs`**. Reminds you to log rationale in **markdown symbol notes** under **`.codeidx/notes/`** (not in `.cs` files).
- **`codeidx hook session-start`** — On session start/resume. Compares the index DB mtime to **`git`**; warns if the index is missing or older than the latest commit.

**Index DB for this repo (from last `init-agents`):** `{db_s}`  
**Repo root:** `{repo_s}`

**Symbol notes (prose):** use the **CLI**, not SQLite MCP:

- `codeidx notes get-or-create <QualifiedName>`
- `codeidx notes append <QualifiedName> --text "…"` or `--from-stdin`
- `codeidx notes sync <QualifiedName>` — refresh the auto-generated sections from the DB

**codeidx MCP** is **read-only**: `read_query`, `list_tables`, `describe_table` only. It does **not** expose `append_insight` or any write/note tool; do not assume one exists.
"""


def merge_codeidx_into_claude_md(
    repo_root: Path,
    db_path: Path,
    *,
    dry_run: bool,
) -> tuple[Path | None, list[str]]:
    """Ensure repo-root CLAUDE.md contains an idempotent codeidx section Claude loads in sessions."""
    messages: list[str] = []
    path = repo_root / "CLAUDE.md"
    section = (
        f"{CODEIDX_CLAUDE_MD_BEGIN}\n"
        f"{_codeidx_claude_md_section(db_path, repo_root).rstrip()}\n"
        f"{CODEIDX_CLAUDE_MD_END}\n"
    )

    if path.is_file():
        text = path.read_text(encoding="utf-8")
        if CODEIDX_CLAUDE_MD_BEGIN in text and CODEIDX_CLAUDE_MD_END in text:
            start = text.index(CODEIDX_CLAUDE_MD_BEGIN)
            end = text.index(CODEIDX_CLAUDE_MD_END) + len(CODEIDX_CLAUDE_MD_END)
            new_text = text[:start].rstrip() + "\n\n" + section + text[end:].lstrip("\n")
        else:
            new_text = text.rstrip() + "\n\n" + section
        if new_text == text:
            messages.append(f"Unchanged {path} (codeidx section)")
            return path, messages
        if dry_run:
            messages.append(f"[dry-run] would update {path} (codeidx section)")
            return path, messages
        path.write_text(new_text, encoding="utf-8")
        messages.append(f"Updated {path} (codeidx section)")
        return path, messages

    if dry_run:
        messages.append(f"[dry-run] would create {path} (codeidx section)")
        return path, messages
    path.write_text(section, encoding="utf-8")
    messages.append(f"Wrote {path} (codeidx section)")
    return path, messages


def merge_claude_settings(
    data: dict[str, Any],
    db_path: Path,
    repo_root: Path,
) -> tuple[dict[str, Any], list[str]]:
    """Merge codeidx hooks into settings dict. Returns (merged, messages)."""
    messages: list[str] = []
    out = dict(data)
    if "$schema" not in out:
        out["$schema"] = "https://json.schemastore.org/claude-code-settings.json"

    hooks = out.get("hooks")
    if hooks is None:
        hooks = {}
        out["hooks"] = hooks
    if not isinstance(hooks, dict):
        raise ValueError("hooks must be an object")

    for key in ("PreToolUse", "PostToolUse", "SessionStart"):
        hooks.setdefault(key, [])
        if not isinstance(hooks[key], list):
            raise ValueError(f"hooks.{key} must be an array")

    defs = build_claude_hook_defs(db_path, repo_root)
    markers = {
        "PreToolUse": MARK_PRE,
        "PostToolUse": MARK_POST,
        "SessionStart": MARK_SESSION,
    }

    for event, groups in defs.items():
        existing: list[Any] = hooks[event]
        for group in groups:
            marker = markers[event]
            if _hook_command_contains(existing, marker):
                messages.append(f"Hook already present ({event}): {marker}")
                continue
            _append_hook_group(existing, group)
            messages.append(f"Added hook group ({event}): {marker}")

    messages.extend(_sync_codeidx_hook_commands(hooks, db_path, repo_root))

    return out, messages


def setup_claude(
    repo_root: Path,
    *,
    db_path: Path,
    dry_run: bool,
) -> ClaudeInitResult:
    settings_path = repo_root / ".claude" / "settings.local.json"
    messages: list[str] = []

    if settings_path.is_file():
        data = read_json_file(settings_path)
    else:
        data = {}

    merged, merge_msgs = merge_claude_settings(data, db_path, repo_root)
    messages.extend(merge_msgs)

    md_path, md_msgs = merge_codeidx_into_claude_md(repo_root, db_path, dry_run=dry_run)
    messages.extend(md_msgs)

    if dry_run:
        messages.append(f"[dry-run] would write {settings_path}")
        return ClaudeInitResult(
            settings_path=settings_path, claude_md_path=md_path, messages=messages
        )

    write_json_file(settings_path, merged)
    messages.append(f"Wrote {settings_path}")
    return ClaudeInitResult(
        settings_path=settings_path, claude_md_path=md_path, messages=messages
    )

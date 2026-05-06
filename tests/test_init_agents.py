from __future__ import annotations

import json
from pathlib import Path
import pytest
from click.testing import CliRunner

from codeidx.agents.claude_setup import MARK_PRE, merge_claude_settings, setup_claude
from codeidx.agents import claude_setup as claude_setup_mod
from codeidx.agents.cursor_setup import setup_cursor
from codeidx.agents.json_util import merge_mcp_server
from codeidx.cli.main import main


def test_merge_mcp_server_add_and_skip() -> None:
    root, action = merge_mcp_server(
        {},
        "codeidx",
        {"command": "python", "args": ["-m", "codeidx", "mcp"]},
        force=False,
    )
    assert action == "add"
    assert root["mcpServers"]["codeidx"]["command"] == "python"
    root2, action2 = merge_mcp_server(
        root,
        "codeidx",
        {"command": "python", "args": ["-m", "codeidx", "mcp"]},
        force=False,
    )
    assert action2 == "skip"


def test_merge_mcp_server_conflict() -> None:
    root, _ = merge_mcp_server(
        {},
        "codeidx",
        {"command": "a"},
        force=False,
    )
    root2, action = merge_mcp_server(
        root,
        "codeidx",
        {"command": "b"},
        force=False,
    )
    assert action == "skip_conflict"
    assert root2["mcpServers"]["codeidx"]["command"] == "a"


def test_setup_claude_writes_claude_md_section(tmp_path: Path) -> None:
    db = tmp_path / "x.db"
    db.write_bytes(b"")
    res = setup_claude(tmp_path, db_path=db, dry_run=False)
    assert res.claude_md_path == tmp_path / "CLAUDE.md"
    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "codeidx hook pre-grep-glob" in text
    assert ".claude/settings.local.json" in text
    assert "get_or_create_note" in text
    assert "append_note" in text
    assert "read-only" in text.lower()


def test_setup_claude_md_section_single_block_after_rerun(tmp_path: Path) -> None:
    db = tmp_path / "x.db"
    db.write_bytes(b"")
    claude = tmp_path / "CLAUDE.md"
    claude.write_text("# Rules\n\nBe concise.\n", encoding="utf-8")
    setup_claude(tmp_path, db_path=db, dry_run=False)
    setup_claude(tmp_path, db_path=db, dry_run=False)
    text = claude.read_text(encoding="utf-8")
    assert text.count("<!-- codeidx init-agents: start -->") == 1
    assert "Be concise." in text


def test_merge_claude_settings_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "x.db"
    db.write_bytes(b"")
    merged, msgs1 = merge_claude_settings({}, db, tmp_path)
    assert any(MARK_PRE in m for m in msgs1)
    merged2, msgs2 = merge_claude_settings(merged, db, tmp_path)
    assert len(msgs2) == 3
    assert all("already present" in m for m in msgs2)
    pre = merged2["hooks"]["PreToolUse"]
    assert sum(1 for g in pre if any(MARK_PRE in str(h.get("command", "")) for h in g.get("hooks", []))) == 1


def test_setup_cursor_writes_files(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite"
    db.write_bytes(b"")
    res = setup_cursor(
        tmp_path,
        db_path=db,
        mcp_server_name="codeidx",
        dry_run=False,
        force=True,
        force_mcp=True,
    )
    assert (tmp_path / ".cursor" / "skills" / "codeidx" / "SKILL.md").is_file()
    assert (tmp_path / ".cursor" / "skills" / "codeidx" / "schema.sql").is_file()
    mcp = json.loads((tmp_path / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert "codeidx" in mcp["mcpServers"]
    assert res.mcp_action in ("add", "update", "skip")


def test_cli_init_agents(tmp_path: Path) -> None:
    db = tmp_path / "d.db"
    db.write_bytes(b"")
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "init-agents",
            str(tmp_path),
            "--db",
            str(db),
            "--agent",
            "cursor",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".cursor" / "mcp.json").is_file()


def test_hook_session_start_warns_stale(tmp_path: Path) -> None:
    from codeidx.cli.hook_cmd import hook_session_start

    db = tmp_path / "db.sqlite"
    db.write_bytes(b"")
    # Make DB old
    import os
    import time

    old = time.time() - 10_000
    os.utime(db, (old, old))

    runner = CliRunner()
    with runner.isolated_filesystem():
        repo = Path("r")
        repo.mkdir()
        subprocess_check = __import__("subprocess").run(
            ["git", "init"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        if subprocess_check.returncode != 0:
            pytest.skip("git not available")
        Path("r/a").write_text("x", encoding="utf-8")
        __import__("subprocess").run(
            ["git", "add", "a"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        __import__("subprocess").run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "m"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        db_path = Path("db.sqlite")
        db_path.write_bytes(b"")
        os.utime(db_path, (old, old))
        inp = json.dumps({"hook_event_name": "SessionStart", "source": "startup"})
        res = runner.invoke(
            hook_session_start,
            ["--db", str(db_path.resolve()), "--repo", str(repo.resolve())],
            input=inp,
        )
    assert res.exit_code == 0
    out = json.loads(res.output.strip())
    assert "stale" in out["hookSpecificOutput"]["additionalContext"].lower() or "older" in out[
        "hookSpecificOutput"
    ]["additionalContext"].lower()


def test_hook_pre_grep_glob_outputs_for_grep() -> None:
    from codeidx.cli.hook_cmd import hook_pre_grep_glob

    runner = CliRunner()
    inp = json.dumps({"tool_name": "Grep", "tool_input": {}})
    res = runner.invoke(hook_pre_grep_glob, input=inp)
    assert res.exit_code == 0
    body = json.loads(res.output.strip())
    assert "hookSpecificOutput" in body
    assert "codeidx" in body["hookSpecificOutput"]["additionalContext"]


def test_merge_claude_upgrades_python_m_hooks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db = tmp_path / "x.db"
    db.write_bytes(b"")
    monkeypatch.setattr(claude_setup_mod.shutil, "which", lambda _x: "/fake/codeidx")
    data = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Grep|Glob",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 -m codeidx hook pre-grep-glob",
                        }
                    ],
                }
            ],
            "PostToolUse": [],
            "SessionStart": [],
        }
    }
    merged, msgs = merge_claude_settings(data, db, tmp_path)
    assert any("Refreshed" in m for m in msgs)
    cmd = merged["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert cmd.startswith("/fake/codeidx")
    assert "hook pre-grep-glob" in cmd
    assert "-m codeidx hook" not in cmd


def test_hook_post_cs_edit() -> None:
    from codeidx.cli.hook_cmd import hook_post_cs_edit

    runner = CliRunner()
    res = runner.invoke(hook_post_cs_edit, input="{}")
    assert res.exit_code == 0
    body = json.loads(res.output.strip())
    ctx = body["hookSpecificOutput"]["additionalContext"]
    assert "C#" in ctx
    assert "append_note" in ctx
    assert "get_or_create_note" in ctx


def test_cli_init_agents_default_db_path(tmp_path: Path) -> None:
    """Without --db, MCP points at <repo>/.codeidx/db/codeidx.db."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "init-agents",
            str(tmp_path),
            "--agent",
            "cursor",
        ],
    )
    assert result.exit_code == 0, result.output
    mcp = json.loads((tmp_path / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    args = mcp["mcpServers"]["codeidx"]["args"]
    expected = str((tmp_path / ".codeidx" / "db" / "codeidx.db").resolve())
    assert expected in args

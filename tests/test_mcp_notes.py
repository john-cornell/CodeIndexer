from __future__ import annotations

from pathlib import Path

import inspect

import pytest

from codeidx.mcp_sqlite import (
    mcp_note_append,
    mcp_note_get_or_create,
    mcp_note_sync_structure,
    run_mcp,
)
from codeidx.notes import NOTES_HEADER

from tests.test_notes import _build_fixture_db


def test_run_mcp_accepts_repo_root() -> None:
    sig = inspect.signature(run_mcp)
    assert set(sig.parameters) == {"db_path", "repo_root"}


def test_mcp_note_get_or_create_format(tmp_path: Path) -> None:
    db = _build_fixture_db(tmp_path)
    out = mcp_note_get_or_create(tmp_path, db, "Demo.Notes.Worker")
    assert out.startswith("Path: ")
    assert "\n\n" in out
    head, body = out.split("\n\n", 1)
    assert head.startswith("Path: ")
    note_path = Path(head.removeprefix("Path: ").strip())
    assert note_path.is_file()
    assert "# Worker" in body
    assert NOTES_HEADER in body


def test_mcp_note_append_format(tmp_path: Path) -> None:
    db = _build_fixture_db(tmp_path)
    mcp_note_get_or_create(tmp_path, db, "Demo.Notes.Worker")
    out = mcp_note_append(tmp_path, "Demo.Notes.Worker", "hello")
    assert out.startswith("Appended under ## Notes:")
    path = tmp_path / ".codeidx" / "notes" / "Demo.Notes.Worker.md"
    assert "hello" in path.read_text(encoding="utf-8")


def test_mcp_note_sync_structure_format(tmp_path: Path) -> None:
    db = _build_fixture_db(tmp_path)
    mcp_note_get_or_create(tmp_path, db, "Demo.Notes.Worker")
    path = tmp_path / ".codeidx" / "notes" / "Demo.Notes.Worker.md"
    path.write_text("# x\n\n## Notes\n- kept\n", encoding="utf-8")
    out = mcp_note_sync_structure(tmp_path, db, "Demo.Notes.Worker")
    assert out.startswith("Synced note structure:")
    text = path.read_text(encoding="utf-8")
    assert "# Worker" in text
    assert "- kept" in text


def test_mcp_note_append_requires_existing_note(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        mcp_note_append(tmp_path, "Missing.Type", "x")

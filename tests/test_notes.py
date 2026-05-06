from __future__ import annotations

from pathlib import Path

import pytest

from codeidx.db.connection import apply_schema, connect
from codeidx.indexer.pipeline import run_index
from codeidx.notes import NOTES_HEADER, append_to_notes_section, get_or_create_note, sync_note_structure


def _build_fixture_db(tmp_path: Path) -> Path:
    src = tmp_path / "NotesFixture.cs"
    src.write_text(
        """
namespace Demo.Notes;

public interface IRepository {}

public class Worker
{
    public Worker(IRepository repository)
    {
    }
}
""".strip(),
        encoding="utf-8",
    )
    db = tmp_path / ".codeidx" / "db" / "codeidx.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    run_index(tmp_path, db, sln=None, csproj=None, store_content=False, force=True)
    return db


def test_get_or_create_note_writes_structure_and_notes_section(tmp_path: Path) -> None:
    db = _build_fixture_db(tmp_path)
    path, text = get_or_create_note(tmp_path, db, "Demo.Notes.Worker")
    assert path.exists()
    assert "# Worker" in text
    assert "## Injected dependencies" in text
    assert NOTES_HEADER in text


def test_get_or_create_note_idempotent_returns_content(tmp_path: Path) -> None:
    db = _build_fixture_db(tmp_path)
    p1, t1 = get_or_create_note(tmp_path, db, "Demo.Notes.Worker")
    p2, t2 = get_or_create_note(tmp_path, db, "Demo.Notes.Worker")
    assert p1 == p2
    assert t1 == t2


def test_sync_note_structure_preserves_notes_section(tmp_path: Path) -> None:
    db = _build_fixture_db(tmp_path)
    path, _ = get_or_create_note(tmp_path, db, "Demo.Notes.Worker")
    path.write_text(
        "# custom top\n\n## Notes\n- keep this\n",
        encoding="utf-8",
    )
    sync_note_structure(tmp_path, db, "Demo.Notes.Worker")
    text = path.read_text(encoding="utf-8")
    assert "# Worker" in text
    assert "## Symbol Info" in text
    assert "## Notes\n- keep this" in text


def test_append_to_notes_section_only_below_header(tmp_path: Path) -> None:
    db = _build_fixture_db(tmp_path)
    path, before = get_or_create_note(tmp_path, db, "Demo.Notes.Worker")
    top = before.split(NOTES_HEADER)[0]
    append_to_notes_section(tmp_path, "Demo.Notes.Worker", "new line")
    after = path.read_text(encoding="utf-8")
    assert after.split(NOTES_HEADER)[0] == top
    assert "new line" in after


def test_append_requires_existing_note(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        append_to_notes_section(tmp_path, "Missing.Type", "x")


def test_append_requires_notes_header(tmp_path: Path) -> None:
    db = _build_fixture_db(tmp_path)
    path, _ = get_or_create_note(tmp_path, db, "Demo.Notes.Worker")
    path.write_text("# only top\nno notes section\n", encoding="utf-8")
    with pytest.raises(ValueError, match=NOTES_HEADER):
        append_to_notes_section(tmp_path, "Demo.Notes.Worker", "x")


def test_symbol_name_is_sanitized_for_filename(tmp_path: Path) -> None:
    db = tmp_path / ".codeidx" / "db" / "codeidx.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db)
    apply_schema(conn)
    conn.close()
    path, _ = get_or_create_note(
        tmp_path,
        db,
        "Demo.Notes.Worker/Inner*Type",
    )
    assert path.name == "Demo.Notes.Worker_Inner_Type.md"


def test_get_or_create_symbol_missing_in_db(tmp_path: Path) -> None:
    db = tmp_path / ".codeidx" / "db" / "codeidx.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db)
    apply_schema(conn)
    conn.close()
    _path, text = get_or_create_note(tmp_path, db, "Unknown.Symbol")
    assert "file_path: `(not found)`" in text

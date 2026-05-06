from __future__ import annotations

from pathlib import Path

from codeidx.indexer.pipeline import run_index
from codeidx.notes import (
    NOTES_HEADER,
    get_or_create_note,
    sync_note_structure,
    update_note,
)


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
    db = tmp_path / "notes.db"
    run_index(tmp_path, db, sln=None, csproj=None, store_content=False, force=True)
    return db


def test_get_or_create_note_writes_structure_and_notes_section(tmp_path: Path) -> None:
    db = _build_fixture_db(tmp_path)
    notes_dir = tmp_path / ".codeidx" / "notes"
    note = get_or_create_note("Demo.Notes.Worker", notes_dir=notes_dir, db_path=db)
    assert note.exists()
    text = note.read_text(encoding="utf-8")
    assert "# Worker" in text
    assert "### Injects" in text
    assert NOTES_HEADER in text


def test_sync_note_structure_preserves_notes_section(tmp_path: Path) -> None:
    db = _build_fixture_db(tmp_path)
    notes_dir = tmp_path / ".codeidx" / "notes"
    note = get_or_create_note("Demo.Notes.Worker", notes_dir=notes_dir, db_path=db)
    note.write_text(
        "# custom top\n\n## Notes\n- keep this\n",
        encoding="utf-8",
    )
    sync_note_structure("Demo.Notes.Worker", notes_dir=notes_dir, db_path=db)
    text = note.read_text(encoding="utf-8")
    assert "# Worker" in text
    assert "## Symbol Info" in text
    assert "## Notes\n- keep this" in text


def test_update_note_replaces_entire_file(tmp_path: Path) -> None:
    notes_dir = tmp_path / ".codeidx" / "notes"
    path = update_note("Demo.Notes.Worker", "hello", notes_dir=notes_dir)
    assert path.read_text(encoding="utf-8") == "hello"


def test_symbol_name_is_sanitized_for_filename(tmp_path: Path) -> None:
    notes_dir = tmp_path / ".codeidx" / "notes"
    note = get_or_create_note(
        "Demo.Notes.Worker/Inner*Type",
        notes_dir=notes_dir,
        db_path=None,
    )
    assert note.name == "Demo.Notes.Worker_Inner_Type.md"


def test_get_or_create_without_db_uses_empty_structure(tmp_path: Path) -> None:
    notes_dir = tmp_path / ".codeidx" / "notes"
    note = get_or_create_note("Unknown.Symbol", notes_dir=notes_dir, db_path=None)
    text = note.read_text(encoding="utf-8")
    assert "qualified_name: `Unknown.Symbol`" in text
    assert "file_path: `(not found)`" in text

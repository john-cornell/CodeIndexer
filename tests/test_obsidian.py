from __future__ import annotations

from pathlib import Path

from codeidx.cli.obsidian import generate_vault
from codeidx.db.connection import apply_schema, connect
from codeidx.indexer.pipeline import run_index


def test_generate_vault_writes_type_markdown_with_wikilinks(tmp_path: Path) -> None:
    src = tmp_path / "VaultFixture.cs"
    src.write_text(
        """
namespace Demo.Vault;

public interface IRepository {}
public class Repository : IRepository {}

public class Worker
{
    private readonly IRepository _repo;

    public Worker(IRepository repo)
    {
        _repo = repo;
    }

    public void Run()
    {
        var r = new Repository();
    }
}
""".strip(),
        encoding="utf-8",
    )
    db = tmp_path / "vault.db"
    run_index(tmp_path, db, sln=None, csproj=None, store_content=False, force=True)

    out_dir = tmp_path / "vault"
    count = generate_vault(db, out_dir)
    assert count >= 3

    worker_note = out_dir / "Demo" / "Vault" / "Worker.md"
    assert worker_note.exists()
    text = worker_note.read_text(encoding="utf-8")
    assert "[[Demo/Vault/IRepository]]" in text


def test_generate_vault_empty_db_writes_no_notes(tmp_path: Path) -> None:
    db = tmp_path / "empty-vault.db"
    conn = connect(db)
    apply_schema(conn)
    conn.close()

    out_dir = tmp_path / "vault-empty"
    count = generate_vault(db, out_dir)
    assert count == 0

from __future__ import annotations

from pathlib import Path

import pytest

from codeidx.cli import query_cmd
from codeidx.db.connection import apply_schema, connect
from codeidx.indexer.pipeline import run_index


@pytest.fixture
def fixture_root() -> Path:
    return Path(__file__).resolve().parent / "fixtures"


def test_index_sample_fixture(tmp_path: Path, fixture_root: Path) -> None:
    db = tmp_path / "idx.db"
    stats = run_index(fixture_root, db, sln=None, csproj=None, store_content=False)
    assert stats.files_parsed >= 1
    assert stats.symbols_written >= 1
    conn = connect(db, create=False)
    n = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    assert int(n) >= 1
    conn.close()


def test_implementations_include_interface_only_base(tmp_path: Path, fixture_root: Path) -> None:
    """`class C : IFace` must appear in implementations-of for IFace (not only `implements` edges)."""
    db = tmp_path / "impl.db"
    run_index(fixture_root, db, sln=None, csproj=None, store_content=False)
    conn = connect(db, create=False)
    row = conn.execute(
        "SELECT id FROM symbols WHERE qualified_name = 'Demo.App.IWorker' LIMIT 1"
    ).fetchone()
    assert row is not None
    iface_id = int(row[0])
    conn.close()
    impls = query_cmd.cmd_implementations_of(db, symbol_id=iface_id, limit=50)
    qnames = {r["qualified_name"] for r in impls}
    assert "Demo.App.Worker" in qnames
    assert "Demo.App.InterfaceOnlyImpl" in qnames


def test_reject_empty_database_file(tmp_path: Path) -> None:
    empty = tmp_path / "empty.db"
    empty.write_bytes(b"")
    with pytest.raises(ValueError, match="empty"):
        connect(empty, create=False)


def test_schema_apply_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "s.db"
    conn = connect(db)
    apply_schema(conn)
    apply_schema(conn)
    conn.close()


def test_parse_csproj_minimal(tmp_path: Path) -> None:
    from codeidx.projects.msbuild import parse_csproj

    p = tmp_path / "a.csproj"
    p.write_text(
        '<Project Sdk="Microsoft.NET.Sdk">'
        '<ItemGroup>'
        '<ProjectReference Include="..\\\\lib\\\\lib.csproj" />'
        '<PackageReference Include="Newtonsoft.Json" Version="13.0.1" />'
        "</ItemGroup></Project>",
        encoding="utf-8",
    )
    info = parse_csproj(p)
    assert any("lib.csproj" in str(x) for x in info.project_references)
    assert "Newtonsoft.Json" in info.package_references

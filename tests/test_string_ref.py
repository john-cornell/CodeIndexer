from __future__ import annotations

from pathlib import Path

from codeidx.db.connection import connect
from codeidx.indexer.pipeline import run_index


def _fixture_root() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "string_ref"


def test_string_ref_edge_when_flag_on(tmp_path: Path) -> None:
    db = tmp_path / "sr.db"
    run_index(
        _fixture_root(),
        db,
        sln=None,
        csproj=None,
        store_content=False,
        force=True,
        index_string_literals=True,
    )
    conn = connect(db, create=False)
    dst = conn.execute(
        "SELECT id FROM symbols WHERE name = 'StringRefMarkerType' AND kind = 'type'"
    ).fetchone()
    assert dst is not None
    did = int(dst[0])
    row = conn.execute(
        """SELECT e.edge_type, e.dst_symbol_id, e.confidence
           FROM edges e
           JOIN symbols s ON s.id = e.src_symbol_id
           WHERE e.edge_type = 'string_ref' AND e.dst_symbol_id = ?
             AND s.qualified_name LIKE '%StringRefConsumer%'""",
        (did,),
    ).fetchone()
    assert row is not None
    assert str(row[0]) == "string_ref"
    conn.close()


def test_string_ref_off_by_default(tmp_path: Path) -> None:
    db = tmp_path / "sr2.db"
    run_index(
        _fixture_root(),
        db,
        sln=None,
        csproj=None,
        force=True,
        index_string_literals=False,
    )
    conn = connect(db, create=False)
    n = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE edge_type = 'string_ref'"
    ).fetchone()
    assert int(n[0]) == 0
    conn.close()

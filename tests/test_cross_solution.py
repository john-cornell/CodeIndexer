from __future__ import annotations

from pathlib import Path

from codeidx.db.connection import connect
from codeidx.indexer.pipeline import run_index


def test_cross_project_interface_implements_resolves_dst(tmp_path: Path) -> None:
    """Class in App implements interface in Lib: dst_symbol_id and implements edge."""
    root = Path(__file__).resolve().parent / "fixtures" / "cross_sln"
    sln = root / "cross_sln.sln"
    db = tmp_path / "cross.db"
    run_index(
        root,
        db,
        sln=sln,
        csproj=None,
        store_content=False,
        force=True,
    )
    conn = connect(db, create=False)
    iface = conn.execute(
        "SELECT id FROM symbols WHERE qualified_name = ? AND kind = 'interface'",
        ("Cross.Fixture.Lib.IIntegrationTarget",),
    ).fetchone()
    assert iface is not None
    iid = int(iface[0])
    row = conn.execute(
        """SELECT e.edge_type, e.confidence, e.dst_symbol_id
           FROM edges e
           JOIN symbols s ON s.id = e.src_symbol_id
           WHERE s.qualified_name = 'Cross.Fixture.App.MyobIntegrationTarget'
             AND e.dst_symbol_id = ?""",
        (iid,),
    ).fetchone()
    assert row is not None
    assert str(row[0]) == "implements"
    assert str(row[1]) in ("exact", "heuristic")
    conn.close()

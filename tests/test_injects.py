from __future__ import annotations

from pathlib import Path

from codeidx.db.connection import connect
from codeidx.indexer.pipeline import run_index


def test_constructor_injects_edge_emitted_and_resolved(tmp_path: Path) -> None:
    src = tmp_path / "InjectFixture.cs"
    src.write_text(
        """
namespace Demo.Injects;

public interface IRepository {}
public interface ILogger {}

public class Service
{
    public Service(IRepository repository, ILogger logger)
    {
    }
}
""".strip(),
        encoding="utf-8",
    )
    db = tmp_path / "injects.db"
    run_index(tmp_path, db, sln=None, csproj=None, store_content=False, force=True)

    conn = connect(db, create=False)
    src_sym = conn.execute(
        "SELECT id FROM symbols WHERE qualified_name = 'Demo.Injects.Service' LIMIT 1"
    ).fetchone()
    assert src_sym is not None
    service_id = int(src_sym[0])

    dst_repo = conn.execute(
        "SELECT id FROM symbols WHERE qualified_name = 'Demo.Injects.IRepository' LIMIT 1"
    ).fetchone()
    assert dst_repo is not None
    repo_id = int(dst_repo[0])

    dst_logger = conn.execute(
        "SELECT id FROM symbols WHERE qualified_name = 'Demo.Injects.ILogger' LIMIT 1"
    ).fetchone()
    assert dst_logger is not None
    logger_id = int(dst_logger[0])

    rows = conn.execute(
        """
        SELECT edge_type, dst_symbol_id, confidence, meta_json
        FROM edges
        WHERE src_symbol_id = ? AND edge_type = 'injects'
        ORDER BY ref_start_col
        """,
        (service_id,),
    ).fetchall()
    conn.close()

    assert len(rows) == 2
    assert {int(r[1]) for r in rows} == {repo_id, logger_id}
    assert all(str(r[0]) == "injects" for r in rows)
    assert all(str(r[2]) in ("exact", "heuristic") for r in rows)

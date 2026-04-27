from __future__ import annotations

from pathlib import Path

from codeidx.cli import query_cmd
from codeidx.db.connection import connect
from codeidx.indexer.pipeline import run_index
from codeidx.layers import build_conceptual, build_semantic, enrich_with_llm


def _fixture_root() -> Path:
    return Path(__file__).resolve().parent / "fixtures"


def test_build_semantic_and_conceptual(tmp_path: Path) -> None:
    db = tmp_path / "layers.db"
    run_index(_fixture_root(), db, sln=None, csproj=None, store_content=False, force=True)
    conn = connect(db, create=False)
    sem = build_semantic(conn)
    con = build_conceptual(conn)
    conn.commit()
    ccount = int(conn.execute("SELECT COUNT(*) FROM semantic_components").fetchone()[0])
    tcount = int(conn.execute("SELECT COUNT(*) FROM conceptual_terms").fetchone()[0])
    conn.close()
    assert sem.rows_written >= 1
    assert con.rows_written >= 1
    assert ccount >= 1
    assert tcount >= 1


def test_query_drill_concept_component_flow(tmp_path: Path) -> None:
    db = tmp_path / "query_layers.db"
    run_index(_fixture_root(), db, sln=None, csproj=None, store_content=False, force=True)
    conn = connect(db, create=False)
    build_semantic(conn)
    build_conceptual(conn)
    conn.commit()
    term_row = conn.execute(
        "SELECT term FROM conceptual_terms ORDER BY score DESC, term LIMIT 1"
    ).fetchone()
    comp_row = conn.execute("SELECT id FROM semantic_components ORDER BY id LIMIT 1").fetchone()
    group_row = conn.execute(
        "SELECT id FROM conceptual_synonym_groups ORDER BY id LIMIT 1"
    ).fetchone()
    conn.close()
    assert term_row is not None
    assert comp_row is not None
    assert group_row is not None
    concept_rows = query_cmd.cmd_query_concept(db, term=str(term_row[0]), limit=10)
    component = query_cmd.cmd_query_component(
        db, component_id=int(comp_row[0]), limit=10
    )
    flows = query_cmd.cmd_query_flow(db, component_id=int(comp_row[0]), group_id=None, limit=10)
    flows_for_group = query_cmd.cmd_query_flow(
        db, component_id=None, group_id=int(group_row[0]), limit=10
    )
    assert concept_rows
    assert component["component"] is not None
    assert isinstance(flows, list)
    assert isinstance(flows_for_group, list)


def test_enrichment_provider_none_is_noop(tmp_path: Path) -> None:
    db = tmp_path / "enrich.db"
    run_index(_fixture_root(), db, sln=None, csproj=None, store_content=False, force=True)
    conn = connect(db, create=False)
    build_semantic(conn)
    conn.commit()
    result = enrich_with_llm(conn, provider="none", model="none")
    conn.commit()
    count = int(conn.execute("SELECT COUNT(*) FROM enrichment_provenance").fetchone()[0])
    conn.close()
    assert result.rows_written == 0
    assert count == 0


def test_enrichment_records_provenance(tmp_path: Path) -> None:
    db = tmp_path / "enrich_cloud.db"
    run_index(_fixture_root(), db, sln=None, csproj=None, store_content=False, force=True)
    conn = connect(db, create=False)
    build_semantic(conn)
    conn.commit()
    result = enrich_with_llm(conn, provider="ollama", model="llama3")
    conn.commit()
    count = int(conn.execute("SELECT COUNT(*) FROM enrichment_provenance").fetchone()[0])
    summary_count = int(
        conn.execute(
            "SELECT COUNT(*) FROM semantic_components WHERE llm_summary IS NOT NULL"
        ).fetchone()[0]
    )
    conn.close()
    assert result.rows_written >= 1
    assert count >= 1
    assert summary_count >= 1

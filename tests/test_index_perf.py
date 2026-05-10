"""Indexing performance and equivalence tests (sequential vs parallel)."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeidx.db.connection import connect
from codeidx.indexer.pipeline import run_index


@pytest.fixture
def fixture_root() -> Path:
    return Path(__file__).resolve().parent / "fixtures"


def test_parallel_index_matches_sequential_counts(
    tmp_path: Path, fixture_root: Path
) -> None:
    db_seq = tmp_path / "sequential.db"
    db_par = tmp_path / "parallel.db"
    run_index(
        fixture_root,
        db_seq,
        sln=None,
        csproj=None,
        store_content=False,
        force=True,
        parallel_workers=1,
    )
    run_index(
        fixture_root,
        db_par,
        sln=None,
        csproj=None,
        store_content=False,
        force=True,
        parallel_workers=2,
    )
    c1 = connect(db_seq, create=False)
    c2 = connect(db_par, create=False)
    try:
        for table in ("symbols", "edges", "files"):
            n1 = int(c1.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            n2 = int(c2.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            assert n1 == n2, f"{table}: sequential={n1} parallel={n2}"
    finally:
        c1.close()
        c2.close()

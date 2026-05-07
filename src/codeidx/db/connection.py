from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path


def _schema_sql() -> str:
    pkg = "codeidx.db"
    with resources.files(pkg).joinpath("schema.sql").open("r", encoding="utf-8") as f:
        return f.read()


def connect(db_path: Path | str, *, create: bool = True) -> sqlite3.Connection:
    path = Path(db_path)
    if not create and not path.is_file():
        raise FileNotFoundError(f"Database not found: {path}")
    if not create and path.is_file() and path.stat().st_size == 0:
        raise ValueError(
            f"Database file is empty (0 bytes): {path}\n"
            "Re-index from the repository root: `python -m codeidx index` (default DB: "
            "`<repo>/.codeidx/db/codeidx.db`), or pass `--db` to the path you use for indexing."
        )
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA cache_size = -64000")
    return conn


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Apply additive DDL for databases created before new columns/tables."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='projects'"
    ).fetchone()
    if row:
        cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(projects)").fetchall()}
        if "domain" not in cols:
            conn.execute("ALTER TABLE projects ADD COLUMN domain TEXT")

    _migrate_features_unique_viewmodel(conn)


def _migrate_features_unique_viewmodel(conn: sqlite3.Connection) -> None:
    """Replace UNIQUE(name, project) with UNIQUE(viewmodel) when upgrading old DBs."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='features'"
    ).fetchone()
    if not row or not row[0]:
        return
    sql = str(row[0])
    compact = sql.replace(" ", "")
    if "UNIQUE(viewmodel)" in compact:
        return
    if "UNIQUE(name,project)" not in compact and "UNIQUE(name, project)" not in sql:
        return
    conn.executescript(
        """
        CREATE TABLE features__new (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          domain TEXT,
          viewmodel TEXT NOT NULL,
          service TEXT,
          project TEXT,
          UNIQUE (viewmodel)
        );
        INSERT INTO features__new (id, name, domain, viewmodel, service, project)
          SELECT id, name, domain, viewmodel, service, project FROM features;
        DROP TABLE features;
        ALTER TABLE features__new RENAME TO features;
        CREATE INDEX IF NOT EXISTS idx_features_name ON features(name);
        CREATE INDEX IF NOT EXISTS idx_features_project ON features(project);
        """
    )


def apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_schema_sql())
    _migrate_schema(conn)
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )

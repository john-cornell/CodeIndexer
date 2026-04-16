from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path
from typing import Any


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
            "Use the database path from your last `python -m codeidx index` run (see README for "
            "the default location on your OS), or re-index the repo."
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


def apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_schema_sql())
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )

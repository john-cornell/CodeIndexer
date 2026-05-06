from __future__ import annotations

import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

_IDENT_SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def _validate_sql_readonly(sql: str) -> None:
    s = sql.strip()
    if not s:
        raise ValueError("Empty query")
    head = s.lstrip().split(None, 1)[0].upper()
    if head not in ("SELECT", "WITH"):
        raise ValueError("Only SELECT or WITH queries are allowed (use describe_table for schema).")


def _validate_table_name(name: str) -> str:
    if not name or not all(c in _IDENT_SAFE for c in name):
        raise ValueError("Invalid table name")
    return name


def run_mcp(db_path: Path) -> None:
    path = db_path.resolve()
    if not path.is_file():
        raise SystemExit(f"Database file not found: {path}")

    uri = path.as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    mcp = FastMCP("codeidx")

    @mcp.tool()
    def read_query(query: str) -> str:
        """Run a read-only SQL query against the codeidx database."""
        _validate_sql_readonly(query)
        cur = conn.execute(query)
        rows = cur.fetchmany(500)
        if not cur.description:
            return "OK"
        cols = [d[0] for d in cur.description]
        lines = ["\t".join(cols)]
        for row in rows:
            lines.append("\t".join("" if v is None else str(v) for v in row))
        more = cur.fetchone()
        tail = ""
        if more is not None or len(rows) == 500:
            tail = "\n… (truncated; add LIMIT)"
        return "\n".join(lines) + tail

    @mcp.tool()
    def list_tables() -> str:
        """List tables and views in the codeidx database."""
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
        )
        return "\n".join(r[0] for r in cur.fetchall())

    @mcp.tool()
    def describe_table(table_name: str) -> str:
        """Return CREATE SQL and column names for a table or view."""
        t = _validate_table_name(table_name)
        cur = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
            (t,),
        )
        row = cur.fetchone()
        if not row or row[0] is None:
            return f"Not found: {t}"
        cur2 = conn.execute(f"PRAGMA table_info({t})")
        cols = cur2.fetchall()
        col_lines = [f"  {c[1]} {c[2]}" for c in cols]
        return row[0] + "\n\nColumns:\n" + "\n".join(col_lines)

    mcp.run(transport="stdio")

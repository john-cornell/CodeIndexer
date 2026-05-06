from __future__ import annotations

import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from codeidx.notes import (
    append_to_notes_section,
    get_or_create_note as _get_or_create_note,
    sync_note_structure as _sync_note_structure,
)

_IDENT_SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def mcp_note_get_or_create(repo_root: Path, db_path: Path, symbol_name: str) -> str:
    """Format output for the ``get_or_create_note`` MCP tool (delegates to ``codeidx.notes``)."""
    path, content = _get_or_create_note(repo_root, db_path, symbol_name)
    return f"Path: {path}\n\n{content}"


def mcp_note_append(repo_root: Path, symbol_name: str, text: str) -> str:
    """Format output for the ``append_note`` MCP tool."""
    path = append_to_notes_section(repo_root, symbol_name, text)
    return f"Appended under ## Notes: {path}"


def mcp_note_sync_structure(repo_root: Path, db_path: Path, symbol_name: str) -> str:
    """Format output for the ``sync_note_structure`` MCP tool."""
    path = _sync_note_structure(repo_root, db_path, symbol_name)
    return f"Synced note structure: {path}"


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


def run_mcp(db_path: Path, repo_root: Path) -> None:
    db_file = db_path.resolve()
    repo = repo_root.resolve()
    if not db_file.is_file():
        raise SystemExit(f"Database file not found: {db_file}")

    uri = db_file.as_uri() + "?mode=ro"
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

    @mcp.tool()
    def get_or_create_note(symbol_name: str) -> str:
        """Open or create a symbol markdown note under .codeidx/notes/.

        Returns a line ``Path: <file>`` then a blank line then the full file contents.
        Use ``append_note`` to add prose under ``## Notes``. If the note file did not exist,
        this creates it with auto-generated structure from the index plus an empty ``## Notes`` section.
        """
        return mcp_note_get_or_create(repo, db_file, symbol_name)

    @mcp.tool()
    def append_note(symbol_name: str, text: str) -> str:
        """Append text below the ``## Notes`` heading in the symbol note file.

        The note must already exist; call ``get_or_create_note`` first if unsure.
        """
        return mcp_note_append(repo, symbol_name, text)

    @mcp.tool()
    def sync_note_structure(symbol_name: str) -> str:
        """Rebuild the auto-generated top of the symbol note from the index; keeps ``## Notes`` onward."""
        return mcp_note_sync_structure(repo, db_file, symbol_name)

    mcp.run(transport="stdio")

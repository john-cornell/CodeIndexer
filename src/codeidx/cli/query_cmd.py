from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from codeidx.db.connection import connect


def _open(db_path: Path) -> sqlite3.Connection:
    return connect(db_path, create=False)


def cmd_find_symbol(
    db_path: Path,
    *,
    name: str | None,
    kind: str | None,
    file_glob: str | None,
    limit: int,
) -> list[sqlite3.Row]:
    conn = _open(db_path)
    clauses: list[str] = []
    params: list[object] = []
    if name:
        clauses.append("(s.name = ? OR s.qualified_name LIKE ?)")
        params.extend([name, f"%{name}%"])
    if kind:
        clauses.append("s.kind = ?")
        params.append(kind)
    if file_glob:
        clauses.append("f.path LIKE ?")
        params.append(file_glob.replace("*", "%"))
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    q = f"""SELECT s.id, s.kind, s.name, s.qualified_name, f.path,
            s.span_start_line, s.span_end_line
            FROM symbols s JOIN files f ON f.id = s.file_id{where}
            ORDER BY f.path, s.span_start_line LIMIT ?"""
    params.append(limit)
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return rows


def cmd_find_references(
    db_path: Path,
    *,
    symbol_id: int | None,
    qualified: str | None,
    limit: int,
) -> list[sqlite3.Row]:
    conn = _open(db_path)
    sid = symbol_id
    if sid is None and qualified:
        r = conn.execute(
            "SELECT id FROM symbols WHERE qualified_name = ? OR name = ? LIMIT 2",
            (qualified, qualified),
        ).fetchall()
        if len(r) == 1:
            sid = int(r[0][0])
    if sid is None:
        conn.close()
        return []
    rows = conn.execute(
        """SELECT e.id, e.edge_type, e.confidence, e.src_file_id, f.path,
           e.ref_start_line, e.ref_start_col, e.dst_symbol_id
           FROM edges e JOIN files f ON f.id = e.src_file_id
           WHERE e.dst_symbol_id = ?
           ORDER BY f.path, e.ref_start_line LIMIT ?""",
        (sid, limit),
    ).fetchall()
    conn.close()
    return rows


def cmd_callers_of(db_path: Path, *, symbol_id: int, limit: int) -> list[sqlite3.Row]:
    conn = _open(db_path)
    rows = conn.execute(
        """SELECT e.id, e.confidence, f.path, e.ref_start_line, e.src_symbol_id,
                  s.qualified_name AS src_q
           FROM edges e
           JOIN files f ON f.id = e.src_file_id
           LEFT JOIN symbols s ON s.id = e.src_symbol_id
           WHERE e.edge_type = 'calls' AND e.dst_symbol_id = ?
           ORDER BY f.path, e.ref_start_line LIMIT ?""",
        (symbol_id, limit),
    ).fetchall()
    conn.close()
    return rows


def cmd_implementations_of(db_path: Path, *, symbol_id: int, limit: int) -> list[sqlite3.Row]:
    conn = _open(db_path)
    # Include legacy rows mislabeled as inherits when the only base was an interface
    # (see TRADEOFFS / pipeline _inheritance_edge_type).
    rows = conn.execute(
        """SELECT s.id, s.kind, s.name, s.qualified_name, f.path,
                  s.span_start_line
           FROM edges e
           JOIN symbols s ON s.id = e.src_symbol_id
           JOIN symbols d ON d.id = e.dst_symbol_id
           JOIN files f ON f.id = s.file_id
           WHERE e.dst_symbol_id = ?
             AND e.src_symbol_id IS NOT NULL
             AND d.kind = 'interface'
             AND e.edge_type IN ('implements', 'inherits')
           LIMIT ?""",
        (symbol_id, limit),
    ).fetchall()
    conn.close()
    return rows


def cmd_features(
    db_path: Path, *, name: str | None, limit: int
) -> list[sqlite3.Row]:
    conn = _open(db_path)
    if name:
        rows = conn.execute(
            """SELECT id, name, domain, viewmodel, service, project FROM features
               WHERE name LIKE ? ORDER BY COALESCE(domain, ''), name LIMIT ?""",
            (f"%{name}%", limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT id, name, domain, viewmodel, service, project FROM features
               ORDER BY COALESCE(domain, ''), name LIMIT ?""",
            (limit,),
        ).fetchall()
    conn.close()
    return rows


def cmd_index_stats(db_path: Path) -> dict[str, object]:
    conn = _open(db_path)
    meta_rows = conn.execute("SELECT key, value FROM meta ORDER BY key").fetchall()
    meta = {str(r[0]): str(r[1]) for r in meta_rows}
    feat_count = 0
    try:
        feat_count = int(conn.execute("SELECT COUNT(*) FROM features").fetchone()[0])
    except sqlite3.OperationalError:
        pass
    counts = {
        "symbols": int(conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]),
        "edges": int(conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]),
        "files": int(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]),
        "projects": int(conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]),
        "features": feat_count,
    }
    conn.close()
    resolved = db_path.resolve()
    return {
        "db_path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "meta": meta,
        "counts": counts,
    }


def cmd_path_search(db_path: Path, *, substring: str, limit: int) -> list[sqlite3.Row]:
    conn = _open(db_path)
    like = f"%{substring}%"
    rows = conn.execute(
        "SELECT id, path FROM files WHERE path LIKE ? ORDER BY path LIMIT ?",
        (like, limit),
    ).fetchall()
    conn.close()
    return rows


def cmd_grep_text(
    db_path: Path,
    *,
    pattern: str,
    limit: int,
    use_regex: bool,
) -> list[tuple[str, str]]:
    conn = _open(db_path)
    out: list[tuple[str, str]] = []
    if use_regex:
        cre = re.compile(pattern)
        cur = conn.execute("SELECT path, content FROM files WHERE content IS NOT NULL")
        for path, content in cur:
            if content and cre.search(content):
                snippet = content.splitlines()[0][:200] if content else ""
                out.append((str(path), snippet))
                if len(out) >= limit:
                    break
    else:
        like = f"%{pattern}%"
        cur = conn.execute(
            "SELECT path, content FROM files WHERE content IS NOT NULL AND content LIKE ? LIMIT ?",
            (like, limit),
        )
        for path, content in cur:
            out.append((str(path), (content or "")[:200]))
        if not out:
            try:
                safe = pattern.replace('"', '""')
                cur2 = conn.execute(
                    """SELECT path, snippet(file_contents_fts, 1, '[', ']', '…', 48) AS snip
                       FROM file_contents_fts WHERE file_contents_fts MATCH ? LIMIT ?""",
                    (safe, limit),
                )
                for row in cur2:
                    out.append((str(row[0]), str(row[1] or "")))
            except sqlite3.OperationalError:
                pass
    conn.close()
    return out

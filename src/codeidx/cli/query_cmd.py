from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

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


def cmd_index_stats(db_path: Path) -> dict[str, object]:
    conn = _open(db_path)
    meta_rows = conn.execute("SELECT key, value FROM meta ORDER BY key").fetchall()
    meta = {str(r[0]): str(r[1]) for r in meta_rows}
    counts = {
        "symbols": int(conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]),
        "edges": int(conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]),
        "files": int(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]),
        "projects": int(conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]),
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


def cmd_query_concept(
    db_path: Path, *, term: str, limit: int
) -> list[sqlite3.Row]:
    conn = _open(db_path)
    rows = conn.execute(
        """SELECT ct.id, ct.term, ct.score, csg.id AS group_id
           FROM conceptual_terms ct
           LEFT JOIN conceptual_synonym_group_terms csgt ON csgt.term_id = ct.id
           LEFT JOIN conceptual_synonym_groups csg ON csg.id = csgt.group_id
           WHERE ct.term = ? OR ct.normalized = ?
           ORDER BY ct.score DESC
           LIMIT ?""",
        (term, term.lower(), limit),
    ).fetchall()
    conn.close()
    return rows


def cmd_query_component(
    db_path: Path, *, component_id: int, limit: int
) -> dict[str, Any]:
    conn = _open(db_path)
    c = conn.execute(
        """SELECT id, key, name, confidence, llm_summary
           FROM semantic_components WHERE id = ?""",
        (component_id,),
    ).fetchone()
    members = conn.execute(
        """SELECT s.id, s.kind, s.qualified_name, f.path, s.span_start_line
           FROM semantic_component_members scm
           JOIN symbols s ON s.id = scm.symbol_id
           JOIN files f ON f.id = s.file_id
           WHERE scm.component_id = ?
           ORDER BY s.qualified_name
           LIMIT ?""",
        (component_id, limit),
    ).fetchall()
    caps = conn.execute(
        """SELECT phrase, confidence FROM semantic_capabilities
           WHERE component_id = ?
           ORDER BY confidence DESC, phrase
           LIMIT ?""",
        (component_id, limit),
    ).fetchall()
    conn.close()
    return {"component": c, "members": members, "capabilities": caps}


def cmd_query_flow(
    db_path: Path, *, component_id: int | None, group_id: int | None, limit: int
) -> list[sqlite3.Row]:
    conn = _open(db_path)
    if group_id is not None:
        rows = conn.execute(
            """SELECT sf.id, sf.entry_symbol_id, sf.path_signature, sf.confidence
               FROM semantic_flows sf
               JOIN semantic_flow_steps sfs ON sfs.flow_id = sf.id
               WHERE sfs.to_component_id IN (
                 SELECT component_id FROM conceptual_component_links WHERE group_id = ?
               ) OR sfs.from_component_id IN (
                 SELECT component_id FROM conceptual_component_links WHERE group_id = ?
               )
               GROUP BY sf.id
               ORDER BY sf.id
               LIMIT ?""",
            (group_id, group_id, limit),
        ).fetchall()
    elif component_id is not None:
        rows = conn.execute(
            """SELECT sf.id, sf.entry_symbol_id, sf.path_signature, sf.confidence
               FROM semantic_flows sf
               JOIN semantic_flow_steps sfs ON sfs.flow_id = sf.id
               WHERE sfs.from_component_id = ? OR sfs.to_component_id = ?
               GROUP BY sf.id
               ORDER BY sf.id
               LIMIT ?""",
            (component_id, component_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT id, entry_symbol_id, path_signature, confidence
               FROM semantic_flows
               ORDER BY id LIMIT ?""",
            (limit,),
        ).fetchall()
    conn.close()
    return rows


def cmd_query_enrichment(
    db_path: Path,
    *,
    table_name: str | None,
    provider: str | None,
    limit: int,
) -> list[sqlite3.Row]:
    conn = _open(db_path)
    clauses: list[str] = []
    params: list[object] = []
    if table_name:
        clauses.append("ep.table_name = ?")
        params.append(table_name)
    if provider:
        clauses.append("ep.provider = ?")
        params.append(provider)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    q = f"""SELECT ep.id, ep.table_name, ep.row_id, ep.field_name,
                   ep.provider, ep.model_id, ep.prompt_version, ep.created_at,
                   sc.name AS component_name, sc.llm_summary
            FROM enrichment_provenance ep
            LEFT JOIN semantic_components sc
              ON ep.table_name = 'semantic_components' AND sc.id = ep.row_id
            {where}
            ORDER BY ep.id DESC
            LIMIT ?"""
    params.append(limit)
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return rows

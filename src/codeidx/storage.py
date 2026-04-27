from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


@dataclass(frozen=True)
class FileRecord:
    id: int
    path: str
    size: int
    mtime_ns: int
    sha256: str
    language: str


def ensure_folder_chain(conn: sqlite3.Connection, abs_path: Path) -> int:
    """Return folder id for the parent directory of abs_path (file path)."""
    parent = abs_path.parent
    parts: list[Path] = []
    cur = parent
    while True:
        parts.append(cur)
        if cur.parent == cur:
            break
        cur = cur.parent
    parts.reverse()

    parent_id: int | None = None
    folder_id = 0
    for p in parts:
        row = conn.execute("SELECT id FROM folders WHERE path = ?", (str(p),)).fetchone()
        if row:
            folder_id = int(row[0])
            parent_id = folder_id
            continue
        conn.execute(
            "INSERT INTO folders(path, parent_id) VALUES (?, ?)",
            (str(p), parent_id),
        )
        folder_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        parent_id = folder_id
    return folder_id


def get_file_by_path(conn: sqlite3.Connection, path: str) -> FileRecord | None:
    row = conn.execute(
        "SELECT id, path, size, mtime_ns, sha256, language FROM files WHERE path = ?",
        (path,),
    ).fetchone()
    if not row:
        return None
    return FileRecord(
        id=int(row[0]),
        path=str(row[1]),
        size=int(row[2]),
        mtime_ns=int(row[3]),
        sha256=str(row[4]),
        language=str(row[5]),
    )


def upsert_file(
    conn: sqlite3.Connection,
    *,
    path: str,
    folder_id: int,
    size: int,
    mtime_ns: int,
    sha256: str,
    language: str,
    content: str | None,
    store_content: bool,
) -> int:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    content_val = content if store_content else None
    row = conn.execute("SELECT id FROM files WHERE path = ?", (path,)).fetchone()
    if row:
        fid = int(row[0])
        conn.execute(
            """UPDATE files SET folder_id=?, size=?, mtime_ns=?, sha256=?, language=?,
               last_indexed_at=?, content=? WHERE id=?""",
            (folder_id, size, mtime_ns, sha256, language, now, content_val, fid),
        )
        if store_content and content is not None:
            conn.execute("DELETE FROM file_contents_fts WHERE path = ?", (path,))
            conn.execute(
                "INSERT INTO file_contents_fts(path, body) VALUES (?, ?)",
                (path, content),
            )
        return fid
    conn.execute(
        """INSERT INTO files(path, folder_id, size, mtime_ns, sha256, language, last_indexed_at, content)
           VALUES (?,?,?,?,?,?,?,?)""",
        (path, folder_id, size, mtime_ns, sha256, language, now, content_val),
    )
    fid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    if store_content and content is not None:
        conn.execute(
            "INSERT INTO file_contents_fts(path, body) VALUES (?, ?)",
            (path, content),
        )
    return fid


def clear_file_index_data(conn: sqlite3.Connection, file_id: int) -> None:
    conn.execute("DELETE FROM edges WHERE src_file_id = ?", (file_id,))
    conn.execute(
        "DELETE FROM edges WHERE src_symbol_id IN (SELECT id FROM symbols WHERE file_id = ?)",
        (file_id,),
    )
    conn.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))


def insert_symbols_batch(
    conn: sqlite3.Connection,
    file_id: int,
    rows: Sequence[
        tuple[
            str,
            str,
            str,
            str,
            str,
            str,
            str,
            int,
            int,
            int,
            int,
            str | None,
        ]
    ],
) -> list[int]:
    """rows: kind, name, qualified_name, namespace, return_type, parameter_types_json, attributes_json, sl, el, sc, ec, ts_node_id"""
    ids: list[int] = []
    for r in rows:
        conn.execute(
            """INSERT INTO symbols(file_id, kind, name, qualified_name,
               namespace, return_type, parameter_types_json, attributes_json,
               span_start_line, span_end_line, span_start_col, span_end_col, ts_node_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (file_id, *r),
        )
        ids.append(int(conn.execute("SELECT last_insert_rowid()").fetchone()[0]))
    return ids


def insert_edges_batch(
    conn: sqlite3.Connection,
    rows: Iterable[
        tuple[
            int | None,
            int | None,
            int,
            int | None,
            str,
            str,
            int | None,
            int | None,
            int | None,
            int | None,
            str | None,
        ]
    ],
) -> None:
    for (
        src_sym,
        dst_sym,
        src_file,
        dst_file,
        etype,
        conf,
        rl,
        rc,
        rle,
        rce,
        meta,
    ) in rows:
        conn.execute(
            """INSERT INTO edges(src_symbol_id, dst_symbol_id, src_file_id, dst_file_id,
               edge_type, confidence, ref_start_line, ref_start_col, ref_end_line, ref_end_col, meta_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (src_sym, dst_sym, src_file, dst_file, etype, conf, rl, rc, rle, rce, meta),
        )


def upsert_project(
    conn: sqlite3.Connection, *, name: str, path: str, kind: str
) -> int:
    row = conn.execute("SELECT id FROM projects WHERE path = ?", (path,)).fetchone()
    if row:
        conn.execute(
            "UPDATE projects SET name = ?, kind = ? WHERE id = ?",
            (name, kind, int(row[0])),
        )
        return int(row[0])
    conn.execute(
        "INSERT INTO projects(name, path, kind) VALUES (?,?,?)",
        (name, path, kind),
    )
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def link_project_file(conn: sqlite3.Connection, project_id: int, file_id: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO project_files(project_id, file_id) VALUES (?, ?)",
        (project_id, file_id),
    )


def insert_project_edge(
    conn: sqlite3.Connection,
    *,
    src_project_id: int,
    dst_project_id: int | None,
    edge_kind: str,
    target: str | None,
) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO project_edges(src_project_id, dst_project_id, edge_kind, target)
           VALUES (?,?,?,?)""",
        (src_project_id, dst_project_id, edge_kind, target),
    )


def json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

from __future__ import annotations

import re
from pathlib import Path

from codeidx.db.connection import connect

NOTES_DIR = Path(".codeidx/notes")
NOTES_HEADER = "## Notes"


def _safe_name(symbol_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", symbol_name).strip("._-")
    return cleaned or "symbol"


def _note_path(symbol_name: str, notes_dir: Path) -> Path:
    return notes_dir / f"{_safe_name(symbol_name)}.md"


def _find_symbol(conn, symbol_name: str):
    rows = conn.execute(
        """
        SELECT s.id, s.kind, s.name, s.qualified_name, f.path
        FROM symbols s
        JOIN files f ON f.id = s.file_id
        WHERE s.qualified_name = ? OR s.name = ?
        ORDER BY CASE WHEN s.qualified_name = ? THEN 0 ELSE 1 END, s.qualified_name
        LIMIT 1
        """,
        (symbol_name, symbol_name, symbol_name),
    ).fetchall()
    return rows[0] if rows else None


def _collect_symbol_structure(db_path: Path | None, symbol_name: str) -> dict[str, object]:
    data: dict[str, object] = {
        "name": symbol_name,
        "found": False,
        "kind": "",
        "qualified_name": symbol_name,
        "file_path": "",
        "members": [],
        "inherits": [],
        "implements": [],
        "injects": [],
        "calls": [],
    }
    if db_path is None or not db_path.is_file():
        return data

    conn = connect(db_path, create=False)
    symbol = _find_symbol(conn, symbol_name)
    if symbol is None:
        conn.close()
        return data

    sid = int(symbol["id"])
    qname = str(symbol["qualified_name"])
    pattern = qname + ".%"
    data.update(
        {
            "name": str(symbol["name"]),
            "found": True,
            "kind": str(symbol["kind"]),
            "qualified_name": qname,
            "file_path": str(symbol["path"]),
        }
    )
    data["members"] = [
        (str(r["kind"]), str(r["qualified_name"]))
        for r in conn.execute(
            """
            SELECT kind, qualified_name
            FROM symbols
            WHERE qualified_name LIKE ?
              AND kind IN ('method', 'field', 'property', 'constructor')
            ORDER BY kind, qualified_name
            """,
            (pattern,),
        ).fetchall()
    ]
    data["inherits"] = [
        str(r[0])
        for r in conn.execute(
            """
            SELECT dst.qualified_name
            FROM edges e
            JOIN symbols dst ON dst.id = e.dst_symbol_id
            WHERE e.src_symbol_id = ? AND e.edge_type = 'inherits'
            ORDER BY dst.qualified_name
            """,
            (sid,),
        ).fetchall()
    ]
    data["implements"] = [
        str(r[0])
        for r in conn.execute(
            """
            SELECT dst.qualified_name
            FROM edges e
            JOIN symbols dst ON dst.id = e.dst_symbol_id
            WHERE e.src_symbol_id = ? AND e.edge_type = 'implements'
            ORDER BY dst.qualified_name
            """,
            (sid,),
        ).fetchall()
    ]
    data["injects"] = [
        str(r[0])
        for r in conn.execute(
            """
            SELECT dst.qualified_name
            FROM edges e
            JOIN symbols dst ON dst.id = e.dst_symbol_id
            WHERE e.src_symbol_id = ? AND e.edge_type = 'injects'
            ORDER BY dst.qualified_name
            """,
            (sid,),
        ).fetchall()
    ]
    data["calls"] = [
        str(r[0])
        for r in conn.execute(
            """
            SELECT dst.qualified_name
            FROM edges e
            JOIN symbols src ON src.id = e.src_symbol_id
            JOIN symbols dst ON dst.id = e.dst_symbol_id
            WHERE e.edge_type = 'calls' AND src.qualified_name LIKE ?
            ORDER BY dst.qualified_name
            """,
            (pattern,),
        ).fetchall()
    ]
    conn.close()
    return data


def _render_links(items: list[str]) -> list[str]:
    if not items:
        return ["- (none)"]
    uniq = sorted(set(items))
    return [f"- [[{item}]]" for item in uniq]


def _render_structure(symbol_name: str, db_path: Path | None) -> str:
    info = _collect_symbol_structure(db_path, symbol_name)
    members = info["members"]
    assert isinstance(members, list)
    lines: list[str] = [
        f"# {info['name']}",
        "",
        "## Symbol Info",
        f"- name: `{info['name']}`",
        f"- qualified_name: `{info['qualified_name']}`",
        f"- kind: `{info['kind'] or 'unknown'}`",
        f"- file_path: `{info['file_path'] or '(not found)'}`",
        "",
        "## Members",
    ]
    if members:
        for kind, qname in members:
            lines.append(f"- `{kind}` `{qname}`")
    else:
        lines.append("- (none)")
    lines.extend(
        [
            "",
            "## Relationships",
            "",
            "### Inherits",
            *_render_links(info["inherits"]),
            "",
            "### Implements",
            *_render_links(info["implements"]),
            "",
            "### Injects",
            *_render_links(info["injects"]),
            "",
            "### Calls",
            *_render_links(info["calls"]),
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _extract_protected_notes(existing_content: str) -> str:
    for idx, line in enumerate(existing_content.splitlines()):
        if line.strip().lower() == NOTES_HEADER.lower():
            return "\n".join(existing_content.splitlines()[idx:]).rstrip() + "\n"
    return NOTES_HEADER + "\n"


def get_or_create_note(
    symbol_name: str,
    notes_dir: Path = NOTES_DIR,
    db_path: Path | None = None,
) -> Path:
    notes_dir.mkdir(parents=True, exist_ok=True)
    path = _note_path(symbol_name, notes_dir)
    if path.exists():
        return path
    structural = _render_structure(symbol_name, db_path)
    content = structural + "\n" + NOTES_HEADER + "\n"
    path.write_text(content, encoding="utf-8")
    return path


def update_note(symbol_name: str, content: str, notes_dir: Path = NOTES_DIR) -> Path:
    notes_dir.mkdir(parents=True, exist_ok=True)
    path = _note_path(symbol_name, notes_dir)
    path.write_text(content, encoding="utf-8")
    return path


def sync_note_structure(
    symbol_name: str,
    notes_dir: Path = NOTES_DIR,
    db_path: Path | None = None,
) -> Path:
    path = get_or_create_note(symbol_name, notes_dir=notes_dir, db_path=db_path)
    existing = path.read_text(encoding="utf-8")
    protected = _extract_protected_notes(existing)
    structural = _render_structure(symbol_name, db_path)
    path.write_text(structural + "\n" + protected, encoding="utf-8")
    return path

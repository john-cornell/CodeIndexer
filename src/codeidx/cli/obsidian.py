from __future__ import annotations

from pathlib import Path

from codeidx.db.connection import connect


def _wikilink_for_qualified(qualified_name: str) -> str:
    return qualified_name.replace(".", "/")


def _note_path_for_symbol(out_dir: Path, qualified_name: str) -> Path:
    return out_dir / (qualified_name.replace(".", "/") + ".md")


def _render_links(items: list[str]) -> list[str]:
    if not items:
        return ["- (none)"]
    return [f"- [[{_wikilink_for_qualified(item)}]]" for item in sorted(set(items))]


def _render_symbol_markdown(
    *,
    symbol: dict[str, object],
    base_links: list[str],
    inject_links: list[str],
    call_links: list[str],
    method_links: list[str],
) -> str:
    sid = int(symbol["id"])
    kind = str(symbol["kind"])
    name = str(symbol["name"])
    qname = str(symbol["qualified_name"])
    path = str(symbol["path"])
    lines: list[str] = [
        "---",
        f"id: {sid}",
        f"kind: {kind}",
        f"qualified_name: {qname}",
        f"file_path: {path}",
        "---",
        "",
        f"# {name}",
        "",
        "## Inherits / Implements",
        *_render_links(base_links),
        "",
        "## Dependencies (Injects)",
        *_render_links(inject_links),
        "",
        "## Methods",
        *_render_links(method_links),
        "",
        "## Calls",
        *_render_links(call_links),
        "",
    ]
    return "\n".join(lines)


def generate_vault(db_path: Path, out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path, create=False)
    symbols = conn.execute(
        """
        SELECT s.id, s.kind, s.name, s.qualified_name, f.path
        FROM symbols s
        JOIN files f ON f.id = s.file_id
        WHERE s.kind IN ('type', 'interface', 'enum', 'delegate')
        ORDER BY s.qualified_name
        """
    ).fetchall()

    written = 0
    for row in symbols:
        sid = int(row["id"])
        qname = str(row["qualified_name"])
        pattern = qname + ".%"

        bases = [
            str(r[0])
            for r in conn.execute(
                """
                SELECT dst.qualified_name
                FROM edges e
                JOIN symbols dst ON dst.id = e.dst_symbol_id
                WHERE e.src_symbol_id = ? AND e.edge_type IN ('inherits', 'implements')
                ORDER BY dst.qualified_name
                """,
                (sid,),
            ).fetchall()
        ]
        injects = [
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
        calls = [
            str(r[0])
            for r in conn.execute(
                """
                SELECT dst.qualified_name
                FROM edges e
                JOIN symbols src ON src.id = e.src_symbol_id
                JOIN symbols dst ON dst.id = e.dst_symbol_id
                WHERE e.edge_type = 'calls'
                  AND src.qualified_name LIKE ?
                ORDER BY dst.qualified_name
                """,
                (pattern,),
            ).fetchall()
        ]
        methods = [
            str(r[0])
            for r in conn.execute(
                """
                SELECT qualified_name
                FROM symbols
                WHERE kind = 'method' AND qualified_name LIKE ?
                ORDER BY qualified_name
                """,
                (pattern,),
            ).fetchall()
        ]

        symbol = {
            "id": sid,
            "kind": str(row["kind"]),
            "name": str(row["name"]),
            "qualified_name": qname,
            "path": str(row["path"]),
        }
        md = _render_symbol_markdown(
            symbol=symbol,
            base_links=bases,
            inject_links=injects,
            call_links=calls,
            method_links=methods,
        )
        note_path = _note_path_for_symbol(out_dir, qname)
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(md, encoding="utf-8")
        written += 1

    conn.close()
    return written

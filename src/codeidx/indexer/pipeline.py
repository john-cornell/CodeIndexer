from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from codeidx.db.connection import apply_schema, connect
from codeidx.indexer.ignore import build_spec
from codeidx.indexer.symbol_index import SymbolIndex
from codeidx.indexer.walk import FileStat, file_fingerprint, iter_files
from codeidx.languages.base import EdgeRow, LanguageHandler, ParseResult, SymbolRow
from codeidx.languages.csharp import CSharpHandler
from codeidx.projects.msbuild import (
    CsprojInfo,
    collect_csproj_infos_from_solutions,
    discover_solution_files,
    parse_csproj,
    parse_sln,
)
from codeidx.storage import (
    clear_file_index_data,
    ensure_folder_chain,
    get_file_by_path,
    insert_edges_batch,
    insert_project_edge,
    insert_symbols_batch,
    json_dumps,
    link_project_file,
    upsert_file,
    upsert_project,
)


def _parse_cs_file_worker(args: tuple[str, bool]) -> tuple[str, ParseResult | None, str | None]:
    """Parse one .cs file in a worker process. Returns (resolved_path, result, error)."""
    path_str, index_string_literals = args
    path = Path(path_str)
    try:
        text = path.read_bytes()
        handler = CSharpHandler()
        result = handler.parse_file(
            path, text, index_string_literals=index_string_literals
        )
        return path_str, result, None
    except Exception as e:
        return path_str, None, str(e)


def _files_row_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM files").fetchone()
    return int(row[0]) if row else 0


def _handlers() -> list[LanguageHandler]:
    return [CSharpHandler()]


def _handler_for(path: Path, handlers: Sequence[LanguageHandler]) -> LanguageHandler | None:
    for h in handlers:
        if h.can_handle(path):
            return h
    return None


def _pick_project_for_file(
    file_path: Path, csproj_infos: list[CsprojInfo]
) -> CsprojInfo | None:
    best: tuple[int, CsprojInfo] | None = None
    fp = file_path.resolve()
    for info in csproj_infos:
        root = info.path.parent.resolve()
        try:
            fp.relative_to(root)
        except ValueError:
            continue
        depth = len(root.parts)
        if best is None or depth > best[0]:
            best = (depth, info)
    return best[1] if best else None


def _resolve_symbol_id(
    conn: sqlite3.Connection,
    project_file_ids: set[int],
    name: str | None,
    qualified_guess: str | None,
    *,
    symbol_index: SymbolIndex | None = None,
) -> tuple[int | None, str]:
    if symbol_index is not None:
        return symbol_index.resolve_symbol_id(project_file_ids, name, qualified_guess)
    if not name and not qualified_guess:
        return None, "unresolved"
    if qualified_guess:
        rows = conn.execute(
            "SELECT id, file_id FROM symbols WHERE qualified_name = ?",
            (qualified_guess,),
        ).fetchall()
        if len(rows) == 1:
            return int(rows[0][0]), "exact"
        if project_file_ids and rows:
            for sid, fid in rows:
                if int(fid) in project_file_ids:
                    return int(sid), "heuristic"
    cand_name = name or (qualified_guess.split(".")[-1] if qualified_guess else "")
    if not cand_name:
        return None, "unresolved"
    if project_file_ids:
        ph = ",".join("?" * len(project_file_ids))
        q = f"SELECT id, qualified_name, file_id FROM symbols WHERE name = ? AND file_id IN ({ph})"
        rows = conn.execute(q, (cand_name, *sorted(project_file_ids))).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, qualified_name, file_id FROM symbols WHERE name = ? LIMIT 50",
            (cand_name,),
        ).fetchall()
    if not rows:
        return None, "unresolved"
    if len(rows) == 1:
        return int(rows[0][0]), "heuristic"
    if qualified_guess:
        for r in rows:
            qn = str(r[1])
            if qualified_guess in qn or qn.endswith("." + cand_name):
                return int(r[0]), "heuristic"
    return int(rows[0][0]), "heuristic"


def _cs_base_short(base: str) -> str:
    b = base.strip().split("<", 1)[0].strip()
    return b.split(".")[-1].strip() if b else ""


def _string_ref_literal_eligible(literal: str) -> bool:
    if len(literal) < 4:
        return False
    if not literal[0].isupper():
        return False
    return all(c.isalnum() or c == "_" for c in literal)


def _resolve_string_ref_dst(
    conn: sqlite3.Connection,
    literal: str,
    *,
    symbol_index: SymbolIndex | None = None,
) -> tuple[int | None, str]:
    if not _string_ref_literal_eligible(literal):
        return None, "unresolved"
    if symbol_index is not None:
        return symbol_index.resolve_string_ref_dst(literal)
    rows = conn.execute(
        """SELECT id FROM symbols WHERE name = ?
           AND kind IN ('type', 'interface', 'enum', 'delegate')""",
        (literal,),
    ).fetchall()
    if len(rows) != 1:
        return None, "unresolved"
    return int(rows[0][0]), "heuristic"


def _cs_interface_name_heuristic(short: str) -> bool:
    if len(short) < 2:
        return False
    return short[0] == "I" and short[1].isupper()


def _all_indexed_file_ids(conn: sqlite3.Connection) -> set[int]:
    return {int(r[0]) for r in conn.execute("SELECT id FROM files")}


def _resolution_file_ids_for_solution(
    conn: sqlite3.Connection, all_project_ids: list[int]
) -> set[int]:
    if not all_project_ids:
        return set()
    ph = ",".join("?" * len(all_project_ids))
    q = f"SELECT file_id FROM project_files WHERE project_id IN ({ph})"
    return {int(r[0]) for r in conn.execute(q, all_project_ids)}


def _resolve_unique_interface_by_name(
    conn: sqlite3.Connection,
    name: str,
    scope_file_ids: set[int],
    *,
    symbol_index: SymbolIndex | None = None,
) -> int | None:
    if symbol_index is not None:
        return symbol_index.resolve_unique_interface_by_name(name, scope_file_ids)
    rows = conn.execute(
        "SELECT id, file_id FROM symbols WHERE name = ? AND kind = ?",
        (name, "interface"),
    ).fetchall()
    if not rows:
        return None
    if len(rows) == 1:
        return int(rows[0][0])
    if scope_file_ids:
        in_scope = [int(r[0]) for r in rows if int(r[1]) in scope_file_ids]
        if len(in_scope) == 1:
            return in_scope[0]
    return None


def _resolve_inheritance_dst(
    conn: sqlite3.Connection,
    scope_file_ids: set[int],
    base: str,
    short: str,
    *,
    symbol_index: SymbolIndex | None = None,
) -> tuple[int | None, str]:
    if not short:
        return None, "unresolved"
    dst_id, conf = _resolve_symbol_id(
        conn, scope_file_ids, short, base or None, symbol_index=symbol_index
    )
    if dst_id is not None:
        return dst_id, conf
    uid = _resolve_unique_interface_by_name(
        conn, short, scope_file_ids, symbol_index=symbol_index
    )
    if uid is not None:
        return uid, "heuristic"
    return None, "unresolved"


def _symbol_kind(
    conn: sqlite3.Connection,
    symbol_id: int,
    *,
    symbol_index: SymbolIndex | None = None,
) -> str | None:
    if symbol_index is not None:
        return symbol_index.kind(symbol_id)
    row = conn.execute("SELECT kind FROM symbols WHERE id = ?", (symbol_id,)).fetchone()
    return str(row[0]) if row else None


def _inheritance_edge_type_final(
    parser_edge: str,
    dst_id: int | None,
    conn: sqlite3.Connection,
    short: str,
    *,
    symbol_index: SymbolIndex | None = None,
) -> str:
    if dst_id is not None:
        sk = _symbol_kind(conn, dst_id, symbol_index=symbol_index)
        if sk == "interface":
            return "implements"
        return parser_edge
    if _cs_interface_name_heuristic(short):
        return "implements"
    return parser_edge


def _merge_inheritance_meta(
    base_meta: dict | None,
    *,
    short: str,
    dst_id: int | None,
    conn: sqlite3.Connection,
    symbol_index: SymbolIndex | None = None,
) -> str:
    meta: dict = dict(base_meta) if base_meta else {}
    meta["base_short"] = short
    if dst_id is not None:
        meta["base_resolved"] = True
        sk = _symbol_kind(conn, dst_id, symbol_index=symbol_index)
        if sk:
            meta["dst_kind"] = sk
    else:
        meta["base_resolved"] = False
        meta["base_kind_hint"] = (
            "interface" if _cs_interface_name_heuristic(short) else "unknown"
        )
    return json_dumps(meta)


def _repair_unresolved_inheritance_edges(
    conn: sqlite3.Connection, *, symbol_index: SymbolIndex | None = None
) -> int:
    full_scope = _all_indexed_file_ids(conn)
    rows = conn.execute(
        """SELECT id, edge_type, meta_json FROM edges
           WHERE dst_symbol_id IS NULL AND edge_type IN ('implements', 'inherits')
             AND meta_json IS NOT NULL AND meta_json != ''"""
    ).fetchall()
    updated = 0
    for eid, et, mjs in rows:
        try:
            meta = json.loads(str(mjs))
        except json.JSONDecodeError:
            continue
        base = (meta.get("base_text") or "").strip()
        if not base:
            continue
        short = _cs_base_short(base)
        if not short:
            continue
        dst_id, conf = _resolve_inheritance_dst(
            conn, full_scope, base, short, symbol_index=symbol_index
        )
        if dst_id is None:
            new_type = _inheritance_edge_type_final(
                str(et), None, conn, short, symbol_index=symbol_index
            )
            new_meta = _merge_inheritance_meta(
                meta, short=short, dst_id=None, conn=conn, symbol_index=symbol_index
            )
            conn.execute(
                """UPDATE edges SET edge_type = ?, confidence = 'unresolved', meta_json = ?
                   WHERE id = ?""",
                (new_type, new_meta, eid),
            )
            continue
        new_type = _inheritance_edge_type_final(
            str(et), dst_id, conn, short, symbol_index=symbol_index
        )
        new_meta = _merge_inheritance_meta(
            meta, short=short, dst_id=dst_id, conn=conn, symbol_index=symbol_index
        )
        conn.execute(
            """UPDATE edges SET dst_symbol_id = ?, confidence = ?, edge_type = ?, meta_json = ?
               WHERE id = ?""",
            (dst_id, conf, new_type, new_meta, eid),
        )
        updated += 1
    return updated


def _emit_edges(
    conn: sqlite3.Connection,
    file_id: int,
    resolution_file_ids: set[int],
    qname_to_id: dict[str, int],
    rows: list[EdgeRow],
    *,
    symbol_index: SymbolIndex | None = None,
) -> int:
    out: list[
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
    ] = []
    for e in rows:
        src_id = qname_to_id.get(e.src_symbol_name or "", None)
        meta = json_dumps(e.meta) if e.meta else None
        if e.edge_type == "imports":
            out.append(
                (
                    None,
                    None,
                    file_id,
                    None,
                    e.edge_type,
                    e.confidence,
                    e.ref_start_line,
                    e.ref_start_col,
                    e.ref_end_line,
                    e.ref_end_col,
                    meta,
                )
            )
            continue
        simple = None
        if e.meta and isinstance(e.meta, dict):
            simple = e.meta.get("callee_simple")
        if e.edge_type in ("inherits", "implements"):
            base = (e.dst_qualified_guess or "").strip()
            short = _cs_base_short(base)
            dst_id, conf = _resolve_inheritance_dst(
                conn, resolution_file_ids, base, short, symbol_index=symbol_index
            )
            if dst_id is None:
                conf = "unresolved"
            edge_type_out = _inheritance_edge_type_final(
                e.edge_type, dst_id, conn, short, symbol_index=symbol_index
            )
            meta = _merge_inheritance_meta(
                e.meta if isinstance(e.meta, dict) else None,
                short=short,
                dst_id=dst_id,
                conn=conn,
                symbol_index=symbol_index,
            )
            out.append(
                (
                    src_id,
                    dst_id,
                    file_id,
                    None,
                    edge_type_out,
                    conf,
                    e.ref_start_line,
                    e.ref_start_col,
                    e.ref_end_line,
                    e.ref_end_col,
                    meta,
                )
            )
            continue
        if e.edge_type == "calls":
            dst_id, conf = _resolve_symbol_id(
                conn,
                resolution_file_ids,
                str(simple) if simple else None,
                e.dst_qualified_guess,
                symbol_index=symbol_index,
            )
            out.append(
                (
                    src_id,
                    dst_id,
                    file_id,
                    None,
                    e.edge_type,
                    conf,
                    e.ref_start_line,
                    e.ref_start_col,
                    e.ref_end_line,
                    e.ref_end_col,
                    meta,
                )
            )
            continue
        if e.edge_type == "injects":
            dst_id, conf = _resolve_symbol_id(
                conn,
                resolution_file_ids,
                None,
                e.dst_qualified_guess,
                symbol_index=symbol_index,
            )
            out.append(
                (
                    src_id,
                    dst_id,
                    file_id,
                    None,
                    "injects",
                    conf,
                    e.ref_start_line,
                    e.ref_start_col,
                    e.ref_end_line,
                    e.ref_end_col,
                    meta,
                )
            )
            continue
        if e.edge_type == "string_ref":
            lit = (e.dst_qualified_guess or "").strip()
            dst_id, conf = _resolve_string_ref_dst(
                conn, lit, symbol_index=symbol_index
            )
            if dst_id is None:
                continue
            meta = json_dumps(
                {
                    **(dict(e.meta) if e.meta else {}),
                    "string_ref": "unique_type_name_match",
                }
            )
            out.append(
                (
                    src_id,
                    dst_id,
                    file_id,
                    None,
                    "string_ref",
                    conf,
                    e.ref_start_line,
                    e.ref_start_col,
                    e.ref_end_line,
                    e.ref_end_col,
                    meta,
                )
            )
            continue
        dst_id, conf = _resolve_symbol_id(
            conn,
            resolution_file_ids,
            None,
            e.dst_qualified_guess,
            symbol_index=symbol_index,
        )
        out.append(
            (
                src_id,
                dst_id,
                file_id,
                None,
                e.edge_type,
                conf,
                e.ref_start_line,
                e.ref_start_col,
                e.ref_end_line,
                e.ref_end_col,
                meta,
            )
        )
    if out:
        insert_edges_batch(conn, out)
    return len(out)


@dataclass
class IndexStats:
    files_scanned: int = 0
    files_skipped_unchanged: int = 0
    files_parsed: int = 0
    symbols_written: int = 0
    edges_written: int = 0
    bytes_read: int = 0
    elapsed_ms: float = 0.0
    errors: list[str] = field(default_factory=list)
    phase_fingerprint_ms: float = 0.0
    phase_parse_ms: float = 0.0
    phase_db_write_ms: float = 0.0
    phase_repair_ms: float = 0.0


def run_index(
    repo_root: Path,
    db_path: Path,
    *,
    sln: Path | None = None,
    csproj: list[Path] | None = None,
    all_solutions: bool = False,
    store_content: bool = False,
    extra_ignore: list[str] | None = None,
    force: bool = False,
    index_string_literals: bool = False,
    index_mvvm_edges: bool = True,
    progress_callback: Callable[[IndexStats], None] | None = None,
    progress_every: int = 200,
    progress_time_s: float = 8.0,
    parallel_workers: int = 1,
    commit_every_files: int = 500,
    commit_every_s: float = 10.0,
) -> IndexStats:
    stats = IndexStats()
    t0 = time.perf_counter()
    repo_root = repo_root.resolve()
    conn = connect(db_path)
    apply_schema(conn)

    handlers = _handlers()
    spec = build_spec(repo_root, extra_ignore)

    csproj_infos: list[CsprojInfo] = []
    if all_solutions:
        sln_paths = discover_solution_files(repo_root)
        if sln_paths:
            csproj_infos = collect_csproj_infos_from_solutions(
                sln_paths, missing_csproj=stats.errors
            )
    elif sln is not None:
        for _name, cpp in parse_sln(sln.resolve()):
            if cpp.suffix.lower() != ".csproj":
                continue
            cpp = cpp.resolve()
            if not cpp.is_file():
                stats.errors.append(
                    f"solution {sln.name} lists missing .csproj: {cpp}"
                )
                continue
            csproj_infos.append(parse_csproj(cpp))
    elif csproj:
        for cpp in csproj:
            if cpp.suffix.lower() != ".csproj":
                continue
            r = cpp.resolve()
            if not r.is_file():
                stats.errors.append(f"--csproj missing file: {r}")
                continue
            csproj_infos.append(parse_csproj(r))

    proj_id_by_path: dict[str, int] = {}
    for info in csproj_infos:
        pid = upsert_project(
            conn,
            name=info.name,
            path=str(info.path),
            kind="csproj",
            domain=info.domain,
        )
        proj_id_by_path[str(info.path)] = pid
    for info in csproj_infos:
        pid = proj_id_by_path[str(info.path)]
        for pref in info.project_references:
            dst = proj_id_by_path.get(str(pref))
            if dst is None:
                row = conn.execute(
                    "SELECT id FROM projects WHERE path = ?", (str(pref),)
                ).fetchone()
                if row:
                    dst = int(row[0])
            insert_project_edge(
                conn,
                src_project_id=pid,
                dst_project_id=dst,
                edge_kind="project_reference",
                target=str(pref),
            )
        for pkg in info.package_references:
            insert_project_edge(
                conn,
                src_project_id=pid,
                dst_project_id=None,
                edge_kind="package_reference",
                target=pkg,
            )
    conn.commit()

    all_proj_ids = list(proj_id_by_path.values())
    symbol_index = SymbolIndex()
    folder_cache: dict[str, int] = {}
    resolution_file_ids = _resolution_file_ids_for_solution(conn, all_proj_ids)

    skip_hash = force or _files_row_count(conn) == 0
    workers = max(1, parallel_workers)

    exts = {".cs"}
    last_report_t = time.perf_counter()
    last_report_scanned = 0

    files_since_commit = 0
    last_commit_t = time.perf_counter()

    def _maybe_commit(force_flush: bool = False) -> None:
        nonlocal files_since_commit, last_commit_t
        now = time.perf_counter()
        if force_flush or (
            files_since_commit >= commit_every_files
            or (now - last_commit_t) >= commit_every_s
        ):
            conn.commit()
            files_since_commit = 0
            last_commit_t = now

    def _maybe_progress() -> None:
        if progress_callback is None:
            return
        nonlocal last_report_t, last_report_scanned
        now = time.perf_counter()
        if (
            progress_every > 0
            and stats.files_scanned > 0
            and stats.files_scanned % progress_every == 0
        ) or (
            now - last_report_t >= progress_time_s
            and stats.files_scanned > last_report_scanned
        ):
            progress_callback(stats)
            last_report_t = now
            last_report_scanned = stats.files_scanned

    pending_dirty: list[tuple[Path, FileStat, str, int]] = []

    for path in iter_files(repo_root, spec, exts):
        try:
            stats.files_scanned += 1
            rel = str(path.resolve())
            t_fp0 = time.perf_counter()
            try:
                fp = file_fingerprint(path, skip_hash=skip_hash)
            except OSError as e:
                stats.errors.append(f"{rel}: {e}")
                continue
            dt_fp = (time.perf_counter() - t_fp0) * 1000
            stats.phase_fingerprint_ms += dt_fp
            stats.bytes_read += fp.size
            folder_id = ensure_folder_chain(conn, path, folder_cache=folder_cache)
            prev = get_file_by_path(conn, rel)
            if (
                not force
                and prev
                and prev.size == fp.size
                and prev.mtime_ns == fp.mtime_ns
                and prev.sha256 == fp.sha256
            ):
                stats.files_skipped_unchanged += 1
                continue

            h = _handler_for(path, handlers)
            if not h:
                continue

            pending_dirty.append((path, fp, rel, folder_id))
        finally:
            _maybe_progress()

    t_parse0 = time.perf_counter()
    parse_by_rel: dict[str, tuple[ParseResult | None, str | None]] = {}
    if pending_dirty:
        if workers > 1:
            args_list = [
                (str(p.resolve()), index_string_literals) for p, _, _, _ in pending_dirty
            ]
            with ProcessPoolExecutor(max_workers=workers) as ex:
                for path_str, pr, err in ex.map(_parse_cs_file_worker, args_list):
                    parse_by_rel[path_str] = (pr, err)
        else:
            h0 = CSharpHandler()
            for path, _fp, rel, _fid in pending_dirty:
                try:
                    text = path.read_bytes()
                    pr = h0.parse_file(
                        path,
                        text,
                        index_string_literals=index_string_literals,
                    )
                    parse_by_rel[rel] = (pr, None)
                except Exception as e:
                    parse_by_rel[rel] = (None, str(e))
    stats.phase_parse_ms = (time.perf_counter() - t_parse0) * 1000

    last_report_t = time.perf_counter()
    last_report_scanned = stats.files_scanned

    for path, fp, rel, folder_id in pending_dirty:
        try:
            pr, parse_err = parse_by_rel[rel]
            if parse_err:
                stats.errors.append(f"{rel}: parse: {parse_err}")
                continue
            if pr is None:
                stats.errors.append(f"{rel}: parse: empty result")
                continue

            h = _handler_for(path, handlers)
            if not h:
                continue

            t_db0 = time.perf_counter()
            text = path.read_bytes()
            sha256_stored = fp.sha256 or hashlib.sha256(text).hexdigest()
            content = text.decode("utf-8", errors="replace") if store_content else None
            file_id = upsert_file(
                conn,
                path=rel,
                folder_id=folder_id,
                size=fp.size,
                mtime_ns=fp.mtime_ns,
                sha256=sha256_stored,
                language=h.name,
                content=content,
                store_content=store_content,
            )

            ev_rows = conn.execute(
                "SELECT id, qualified_name, name, kind FROM symbols WHERE file_id = ?",
                (file_id,),
            ).fetchall()
            if ev_rows:
                symbol_index.evict_file(
                    [(int(a), str(b), str(c), str(d)) for a, b, c, d in ev_rows]
                )
            clear_file_index_data(conn, file_id)

            sym_rows = [
                (
                    s.kind,
                    s.name,
                    s.qualified_name,
                    s.span_start_line,
                    s.span_end_line,
                    s.span_start_col,
                    s.span_end_col,
                    s.ts_node_id,
                )
                for s in pr.symbols
            ]
            ids = insert_symbols_batch(conn, file_id, sym_rows)
            stats.symbols_written += len(sym_rows)
            symbol_index.register_symbols(file_id, pr.symbols, ids)

            qname_to_id = {
                s.qualified_name: sid
                for s, sid in zip(pr.symbols, ids, strict=True)
            }

            pinfo = _pick_project_for_file(path, csproj_infos)
            if pinfo:
                pid = proj_id_by_path.get(str(pinfo.path))
                if pid is not None:
                    link_project_file(conn, pid, file_id)
                    resolution_file_ids.add(file_id)

            ec = _emit_edges(
                conn,
                file_id,
                resolution_file_ids,
                qname_to_id,
                pr.edges,
                symbol_index=symbol_index,
            )
            stats.edges_written += ec
            stats.files_parsed += 1
            stats.phase_db_write_ms += (time.perf_counter() - t_db0) * 1000

            files_since_commit += 1
            _maybe_commit()
        finally:
            _maybe_progress()

    _maybe_commit(force_flush=True)

    t_rep0 = time.perf_counter()
    _repair_unresolved_inheritance_edges(conn, symbol_index=symbol_index)
    stats.phase_repair_ms = (time.perf_counter() - t_rep0) * 1000
    try:
        from codeidx.features import build_features as _build_features

        _build_features(conn)
    except Exception as e:
        stats.errors.append(f"features inference skipped: {e}")
    if index_mvvm_edges:
        try:
            from codeidx.mvvm_edges import build_mvvm_edges as _build_mvvm_edges

            _build_mvvm_edges(conn, repo_root)
        except Exception as e:
            stats.errors.append(f"mvvm edges skipped: {e}")
    conn.commit()

    dt = (time.perf_counter() - t0) * 1000
    stats.elapsed_ms = dt
    conn.execute(
        "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        ("last_index_ms", str(int(dt))),
    )
    conn.commit()
    conn.close()
    return stats

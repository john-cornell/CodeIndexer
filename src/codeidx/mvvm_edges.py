"""Heuristic MVVM edges emitted in a post-index pass (default on).

View pairing: for each ``*ViewModel`` type in namespace ``Ns``, looks for
``Ns.<Stem>View``, ``Ns.<Stem>Page``, ``Ns.<Stem>Window`` (first match wins).

Primary service: among constructor ``injects`` edges whose ``src_symbol_id`` is
the ViewModel type, pick one target using suffix priority (Service, ServiceAgent,
Manager, Client) then ``parameter_index`` from ``meta_json``.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from codeidx.mvvm_ui import collect_mvvm_ui_edges
from codeidx.storage import insert_edges_batch

_VIEW_SUFFIXES = ("View", "Page", "Window")

_INJECT_RANK = (
    "Service",
    "ServiceAgent",
    "Manager",
    "Client",
)


def _inject_sort_key(dst_name: str, param_index: int) -> tuple[int, int, str]:
    name = dst_name or ""
    rank = 99
    for i, suf in enumerate(_INJECT_RANK):
        if name.endswith(suf):
            rank = i
            break
    return (rank, param_index, name)


def _meta_param_index(meta_json: str | None) -> int:
    if not meta_json:
        return 0
    try:
        m: Any = json.loads(meta_json)
        if isinstance(m, dict) and "parameter_index" in m:
            return int(m["parameter_index"])
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return 0


def build_mvvm_edges(conn: sqlite3.Connection, repo_root: Path | None = None) -> int:
    """Delete prior MVVM edges, then insert ``mvvm_view`` and ``mvvm_primary_service``.

    Also calls UI adapters (e.g. generic.xaml hook) — v1 returns no extra edges.

    Returns the number of edges inserted.
    """
    conn.execute(
        "DELETE FROM edges WHERE edge_type IN ('mvvm_view', 'mvvm_primary_service')"
    )

    vms = conn.execute(
        """
        SELECT id, name, qualified_name, file_id
        FROM symbols
        WHERE kind = 'type' AND name LIKE '%ViewModel'
        ORDER BY qualified_name
        """
    ).fetchall()

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

    vm_ids: list[int] = []

    for row in vms:
        vm_id = int(row["id"])
        sym_name = str(row["name"])
        qname = str(row["qualified_name"])
        stem = sym_name.removesuffix("ViewModel")
        if not stem:
            continue
        ns_prefix = qname.rsplit(".", 1)[0]
        vm_ids.append(vm_id)

        view_id: int | None = None
        view_file_id: int | None = None
        rule: str | None = None
        for suf in _VIEW_SUFFIXES:
            cand = f"{ns_prefix}.{stem}{suf}"
            hit = conn.execute(
                """
                SELECT id, file_id FROM symbols
                WHERE kind = 'type' AND qualified_name = ?
                ORDER BY id LIMIT 2
                """,
                (cand,),
            ).fetchall()
            if len(hit) == 1:
                view_id = int(hit[0]["id"])
                view_file_id = int(hit[0]["file_id"])
                rule = cand.rsplit(".", 1)[-1]
                break
            if len(hit) > 1:
                hit_sorted = sorted(hit, key=lambda r: int(r["id"]))
                view_id = int(hit_sorted[0]["id"])
                view_file_id = int(hit_sorted[0]["file_id"])
                rule = cand.rsplit(".", 1)[-1]
                break

        if view_id is not None and view_file_id is not None:
            meta = json.dumps({"mvvm": "view_pair", "rule": rule})
            out.append(
                (
                    view_id,
                    vm_id,
                    view_file_id,
                    None,
                    "mvvm_view",
                    "heuristic",
                    None,
                    None,
                    None,
                    None,
                    meta,
                )
            )

    for vm_id in vm_ids:
        row_vm = conn.execute(
            "SELECT qualified_name FROM symbols WHERE id = ?", (vm_id,)
        ).fetchone()
        if not row_vm:
            continue
        vm_qname = str(row_vm[0])
        vm_file = conn.execute(
            "SELECT file_id FROM symbols WHERE id = ?", (vm_id,)
        ).fetchone()
        if not vm_file:
            continue
        vm_file_id = int(vm_file[0])

        inject_rows = conn.execute(
            """
            SELECT e.dst_symbol_id, e.meta_json
            FROM edges e
            WHERE e.edge_type = 'injects' AND e.src_symbol_id = ?
              AND e.dst_symbol_id IS NOT NULL
            """,
            (vm_id,),
        ).fetchall()
        if not inject_rows:
            continue

        scored: list[tuple[tuple[int, int, str], int, str | None]] = []
        for ir in inject_rows:
            dst_id = int(ir["dst_symbol_id"])
            pidx = _meta_param_index(str(ir["meta_json"]) if ir["meta_json"] else None)
            drow = conn.execute(
                "SELECT name FROM symbols WHERE id = ?", (dst_id,)
            ).fetchone()
            dst_name = str(drow[0]) if drow else ""
            key = _inject_sort_key(dst_name, pidx)
            meta = json.dumps({"mvvm": "primary_service", "parameter_index": pidx})
            scored.append((key, dst_id, meta))

        scored.sort(key=lambda t: (t[0][0], t[0][1], t[0][2]))
        _key, best_dst, best_meta = scored[0]

        out.append(
            (
                vm_id,
                best_dst,
                vm_file_id,
                None,
                "mvvm_primary_service",
                "heuristic",
                None,
                None,
                None,
                None,
                best_meta,
            )
        )

        svc_row = conn.execute(
            "SELECT qualified_name FROM symbols WHERE id = ?", (best_dst,)
        ).fetchone()
        if svc_row:
            conn.execute(
                "UPDATE features SET service = ? WHERE viewmodel = ?",
                (str(svc_row[0]), vm_qname),
            )

    out.extend(collect_mvvm_ui_edges(repo_root, conn))

    if out:
        insert_edges_batch(conn, out)
    return len(out)

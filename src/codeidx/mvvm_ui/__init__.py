"""Pluggable MVVM UI link discovery (e.g. XAML). v1: stubs only."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from codeidx.mvvm_ui.generic_xaml import discover_mvvm_ui_links as _generic_xaml_links

# Register adapters in call order; each returns edge rows compatible with ``insert_edges_batch``.
MVVM_UI_ADAPTERS: list = [_generic_xaml_links]

EdgeBatchRow = tuple[
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


def collect_mvvm_ui_edges(repo_root: Path | None, conn: sqlite3.Connection) -> list[EdgeBatchRow]:
    rows: list[EdgeBatchRow] = []
    for adapter in MVVM_UI_ADAPTERS:
        rows.extend(adapter(repo_root, conn))
    return rows

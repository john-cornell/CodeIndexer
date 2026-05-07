"""Hook for ``generic.xaml``-driven MVVM links.

v1 returns no edges. Extend ``discover_mvvm_ui_links`` to scan XAML or project
conventions and return rows in ``insert_edges_batch`` shape:
``(src_sym, dst_sym, src_file_id, dst_file, edge_type, conf, rl, rc, rle, rce, meta)``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def discover_mvvm_ui_links(
    repo_root: Path | None,
    conn: sqlite3.Connection,
) -> list:
    del repo_root, conn
    return []

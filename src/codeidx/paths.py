"""Per-repository locations for codeidx data (database, notes, vault)."""

from __future__ import annotations

from pathlib import Path

import click

_DB_FILENAME = "codeidx.db"


def repo_codeidx_dir(repo_root: Path) -> Path:
    return repo_root.resolve() / ".codeidx"


def repo_db_path(repo_root: Path) -> Path:
    """`<repo>/.codeidx/db/codeidx.db` — same path on Windows and WSL for a given repo root."""
    return repo_codeidx_dir(repo_root) / "db" / _DB_FILENAME


def repo_notes_dir(repo_root: Path) -> Path:
    return repo_codeidx_dir(repo_root) / "notes"


def repo_vault_dir(repo_root: Path) -> Path:
    return repo_codeidx_dir(repo_root) / "vault"


def resolve_db_path(repo_root: Path, db_path: Path | None) -> Path:
    """Use explicit ``db_path`` when set; otherwise the per-repo default under ``repo_root``."""
    if db_path is not None:
        return db_path.resolve()
    return repo_db_path(repo_root)


def require_existing_db(path: Path) -> Path:
    p = path.resolve()
    if not p.is_file():
        raise click.ClickException(
            f"Database not found: {p}\n"
            "Expected <repository>/.codeidx/db/codeidx.db — run `codeidx index` from the "
            "repository root (or pass `--db`)."
        )
    return p

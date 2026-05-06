from __future__ import annotations

from pathlib import Path

import click
import pytest

from codeidx.paths import (
    repo_codeidx_dir,
    repo_db_path,
    repo_notes_dir,
    repo_vault_dir,
    require_existing_db,
    resolve_db_path,
)


def test_repo_paths_under_codeidx(tmp_path: Path) -> None:
    r = tmp_path / "myrepo"
    r.mkdir()
    assert repo_codeidx_dir(r) == r.resolve() / ".codeidx"
    assert repo_db_path(r) == r.resolve() / ".codeidx" / "db" / "codeidx.db"
    assert repo_notes_dir(r) == r.resolve() / ".codeidx" / "notes"
    assert repo_vault_dir(r) == r.resolve() / ".codeidx" / "vault"


def test_resolve_db_path_explicit_overrides_repo(tmp_path: Path) -> None:
    r = tmp_path / "r"
    r.mkdir()
    alt = tmp_path / "other.db"
    alt.write_bytes(b"")
    assert resolve_db_path(r, alt) == alt.resolve()
    assert resolve_db_path(r, None) == repo_db_path(r)


def test_require_existing_db_raises_click(tmp_path: Path) -> None:
    missing = tmp_path / "nope.db"
    with pytest.raises(click.ClickException) as exc:
        require_existing_db(missing)
    assert str(missing.resolve()) in str(exc.value)

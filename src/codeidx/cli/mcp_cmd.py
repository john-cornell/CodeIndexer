from __future__ import annotations

from pathlib import Path

import click

from codeidx.mcp_sqlite import run_mcp
from codeidx.paths import require_existing_db, resolve_db_path


@click.command("mcp")
@click.option(
    "--repo",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Repository root (default: current directory). Implies --db under .codeidx/db/.",
)
@click.option(
    "--db",
    "db_path",
    type=click.Path(path_type=Path),
    default=None,
    help="SQLite database (default: <repo>/.codeidx/db/codeidx.db).",
)
def mcp_cmd(repo: Path | None, db_path: Path | None) -> None:
    """Run a stdio MCP server with read-only access to the codeidx SQLite database."""
    repo_root = (repo or Path(".")).resolve()
    resolved = resolve_db_path(repo_root, db_path)
    require_existing_db(resolved)
    run_mcp(resolved)

from __future__ import annotations

from pathlib import Path

import click

from codeidx.agents.claude_setup import setup_claude
from codeidx.agents.cursor_setup import setup_cursor
from codeidx.paths import resolve_db_path


def _normalize_agents(agents: tuple[str, ...]) -> set[str]:
    if "all" in agents:
        return {"cursor", "claude"}
    out = {a for a in agents if a != "all"}
    return out if out else {"cursor", "claude"}


def register_init_agents(main: click.Group) -> None:
    @main.command("init-agents")
    @click.argument(
        "repo",
        type=click.Path(exists=True, file_okay=False, path_type=Path),
        required=False,
    )
    @click.option(
        "--db",
        "db_path",
        type=click.Path(path_type=Path),
        default=None,
        help="codeidx SQLite file (default: <REPO>/.codeidx/db/codeidx.db).",
    )
    @click.option(
        "--agent",
        "agents",
        multiple=True,
        type=click.Choice(["cursor", "claude", "all"], case_sensitive=False),
        default=("all",),
        help="Which integrations to configure (repeatable). Default: all.",
    )
    @click.option(
        "--mcp-name",
        default="codeidx",
        show_default=True,
        help="Cursor mcp.json server name",
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Print actions without writing files",
    )
    @click.option(
        "--force",
        is_flag=True,
        help="Overwrite Cursor skill and schema copy even if unchanged",
    )
    @click.option(
        "--force-mcp",
        is_flag=True,
        help="Replace Cursor MCP server entry if it already exists with a different definition",
    )
    def init_agents_cmd(
        repo: Path | None,
        db_path: Path | None,
        agents: tuple[str, ...],
        mcp_name: str,
        dry_run: bool,
        force: bool,
        force_mcp: bool,
    ) -> None:
        """Configure Cursor (skill + MCP) and/or Claude Code hooks for codeidx."""
        root = (repo or Path(".")).resolve()
        db_resolved = resolve_db_path(root, db_path)
        chosen = _normalize_agents(tuple(a.lower() for a in agents))

        if "cursor" in chosen:
            cur = setup_cursor(
                root,
                db_path=db_resolved,
                mcp_server_name=mcp_name,
                dry_run=dry_run,
                force=force,
                force_mcp=force_mcp,
            )
            for m in cur.messages:
                click.echo(m)

        if "claude" in chosen:
            cl = setup_claude(root, db_path=db_resolved, dry_run=dry_run)
            for m in cl.messages:
                click.echo(m)

        if dry_run:
            click.echo("[dry-run] no files modified.")
        else:
            click.echo("init-agents complete.")

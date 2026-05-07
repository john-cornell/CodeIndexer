from __future__ import annotations

import importlib.resources
from dataclasses import dataclass
from pathlib import Path

from codeidx.agents.json_util import merge_mcp_server, read_json_file, write_json_file
from codeidx.agents.mcp_spec import build_codeidx_stdio_mcp_server_spec


@dataclass
class CursorInitResult:
    skill_path: Path | None
    schema_path: Path | None
    mcp_json_path: Path | None
    mcp_action: str
    messages: list[str]


def _load_bundled_skill_text() -> str:
    return (
        importlib.resources.files("codeidx")
        .joinpath("agents/bundled/cursor/SKILL.md")
        .read_text(encoding="utf-8")
    )


def _load_schema_text() -> str:
    return importlib.resources.files("codeidx").joinpath("db/schema.sql").read_text(encoding="utf-8")


def _should_write(path: Path, new_content: str, *, force: bool) -> bool:
    if force:
        return True
    if not path.is_file():
        return True
    return path.read_text(encoding="utf-8") != new_content


def setup_cursor(
    repo_root: Path,
    *,
    db_path: Path,
    mcp_server_name: str,
    dry_run: bool,
    force: bool,
    force_mcp: bool,
) -> CursorInitResult:
    messages: list[str] = []
    skill_path = repo_root / ".cursor" / "skills" / "codeidx" / "SKILL.md"
    schema_path = repo_root / ".cursor" / "skills" / "codeidx" / "schema.sql"
    mcp_path = repo_root / ".cursor" / "mcp.json"

    skill_text = _load_bundled_skill_text()
    schema_text = _load_schema_text()

    skill_written = False
    schema_written = False
    if dry_run:
        messages.append(f"[dry-run] would ensure {skill_path.parent}")
        if _should_write(skill_path, skill_text, force=force):
            messages.append(f"[dry-run] would write {skill_path}")
            skill_written = True
        else:
            messages.append(f"[dry-run] skip skill (already up to date): {skill_path}")
        if _should_write(schema_path, schema_text, force=force):
            messages.append(f"[dry-run] would write {schema_path}")
            schema_written = True
        else:
            messages.append(f"[dry-run] skip schema (already up to date): {schema_path}")
    else:
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        if _should_write(skill_path, skill_text, force=force):
            skill_path.write_text(skill_text, encoding="utf-8")
            skill_written = True
        if _should_write(schema_path, schema_text, force=force):
            schema_path.write_text(schema_text, encoding="utf-8")
            schema_written = True

    if not dry_run:
        if skill_written:
            messages.append(f"Wrote skill: {skill_path}")
        else:
            messages.append(f"Unchanged (use --force to overwrite): {skill_path}")
        if schema_written:
            messages.append(f"Wrote schema copy: {schema_path}")
        else:
            messages.append(f"Unchanged (use --force to overwrite): {schema_path}")

    server_spec = build_codeidx_stdio_mcp_server_spec(repo_root, db_path)

    mcp_action = "skip"
    if dry_run:
        messages.append(f"[dry-run] would merge MCP server {mcp_server_name!r} into {mcp_path}")
    else:
        if mcp_path.is_file():
            root = read_json_file(mcp_path)
        else:
            root = {}
        root, mcp_action = merge_mcp_server(
            root, mcp_server_name, server_spec, force=force_mcp
        )
        if mcp_action == "skip_conflict":
            messages.append(
                f"Skipped MCP server {mcp_server_name!r}: already present with different "
                f"definition (use --force-mcp to replace)."
            )
        else:
            write_json_file(mcp_path, root)
            if mcp_action == "add":
                messages.append(f"Added MCP server {mcp_server_name!r} in {mcp_path}")
            elif mcp_action == "update":
                messages.append(f"Updated MCP server {mcp_server_name!r} in {mcp_path}")
            else:
                messages.append(f"MCP server {mcp_server_name!r} unchanged in {mcp_path}")

    return CursorInitResult(
        skill_path=skill_path,
        schema_path=schema_path,
        mcp_json_path=mcp_path,
        mcp_action=mcp_action,
        messages=messages,
    )

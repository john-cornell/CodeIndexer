"""Shared stdio MCP server definition for codeidx (Cursor mcp.json and Claude mcpServers)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_codeidx_stdio_mcp_server_spec(repo_root: Path, db_path: Path) -> dict[str, Any]:
    """Same shape as Cursor ``mcp.json`` / Claude ``mcpServers.<name>`` entries."""
    return {
        "command": "python",
        "args": [
            "-m",
            "codeidx",
            "mcp",
            "--repo",
            str(repo_root.resolve()),
            "--db",
            str(db_path.resolve()),
        ],
    }

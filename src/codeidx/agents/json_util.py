from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return data


def write_json_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def merge_mcp_server(
    root: dict[str, Any],
    server_name: str,
    server_spec: dict[str, Any],
    *,
    force: bool,
) -> tuple[dict[str, Any], str]:
    """Return (updated_root, action) where action is skip|update|add."""
    out = dict(root)
    servers = out.get("mcpServers")
    if servers is None:
        servers = {}
        out["mcpServers"] = servers
    if not isinstance(servers, dict):
        raise ValueError("mcpServers must be an object")

    if server_name in servers:
        if servers[server_name] == server_spec:
            return out, "skip"
        if not force:
            return out, "skip_conflict"
        servers[server_name] = server_spec
        return out, "update"
    servers[server_name] = server_spec
    return out, "add"

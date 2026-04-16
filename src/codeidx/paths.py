"""Default locations for codeidx data files."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_DEFAULT_NAME = "codeidx.db"


def default_db_path() -> Path:
    """
    Default SQLite database path.

    - Windows: %LOCALAPPDATA%\\codeidx\\codeidx.db
    - macOS: ~/Library/Application Support/codeidx/codeidx.db
    - Other: ~/.local/share/codeidx/codeidx.db (XDG-style)
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            base = str(Path.home() / "AppData" / "Local")
        return Path(base) / "codeidx" / _DEFAULT_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "codeidx" / _DEFAULT_NAME
    return Path.home() / ".local" / "share" / "codeidx" / _DEFAULT_NAME

from __future__ import annotations

import sys

from codeidx.paths import default_db_path


def test_default_db_path_name_and_parent() -> None:
    p = default_db_path()
    assert p.name == "codeidx.db"
    assert p.parent.name == "codeidx"
    if sys.platform == "win32":
        assert "AppData" in str(p) or "appdata" in str(p).lower()

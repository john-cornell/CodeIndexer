from __future__ import annotations

import sqlite3
from pathlib import Path

from codeidx.cli import query_cmd
from codeidx.cli.obsidian import generate_vault
from codeidx.db.connection import apply_schema, connect
from codeidx.features import build_features
from codeidx.indexer.pipeline import run_index


def test_apply_schema_migrates_features_unique_to_viewmodel(tmp_path: Path) -> None:
    db = tmp_path / "migrate-features.db"
    raw = sqlite3.connect(db)
    raw.execute(
        """
        CREATE TABLE features (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          domain TEXT,
          viewmodel TEXT NOT NULL,
          service TEXT,
          project TEXT,
          UNIQUE (name, project)
        );
        """
    )
    raw.commit()
    raw.close()

    conn = connect(db)
    apply_schema(conn)
    conn.close()

    conn = connect(db, create=False)
    sql = str(
        conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='features'"
        ).fetchone()[0]
    )
    conn.close()
    compact = sql.replace(" ", "")
    assert "UNIQUE(viewmodel)" in compact
    assert "UNIQUE(name,project)" not in compact


def test_build_features_maps_viewmodel_to_service(tmp_path: Path) -> None:
    src = tmp_path / "Features.cs"
    src.write_text(
        """
namespace Demo.App;

public class UserViewModel {}
public class UserService {}
""".strip(),
        encoding="utf-8",
    )
    db = tmp_path / "feat.db"
    run_index(tmp_path, db, sln=None, csproj=None, store_content=False, force=True)

    conn = connect(db, create=False)
    n = build_features(conn)
    conn.commit()
    conn.close()
    assert n >= 1

    conn = connect(db, create=False)
    row = conn.execute(
        "SELECT name, domain, viewmodel, service FROM features WHERE name = ?",
        ("User",),
    ).fetchone()
    conn.close()
    assert row is not None
    assert str(row["viewmodel"]) == "Demo.App.UserViewModel"
    assert str(row["service"]) == "Demo.App.UserService"
    assert str(row["domain"]) == "Demo"

    rows = query_cmd.cmd_features(db, name="User", limit=50)
    assert any(str(r["name"]) == "User" for r in rows)

    out = tmp_path / "vault"
    generate_vault(db, out)
    note = out / "Features" / "User.md"
    assert note.exists()
    text = note.read_text(encoding="utf-8")
    assert "[[Demo/App/UserViewModel]]" in text
    assert "[[Demo/App/UserService]]" in text


def test_features_domain_from_csproj_root_namespace(tmp_path: Path) -> None:
    proj = tmp_path / "App.csproj"
    proj.write_text(
        '<Project Sdk="Microsoft.NET.Sdk">'
        "<PropertyGroup>"
        "<RootNamespace>Acme.Product.Feature</RootNamespace>"
        "</PropertyGroup>"
        "</Project>",
        encoding="utf-8",
    )
    src = tmp_path / "VM.cs"
    src.write_text(
        """
namespace Acme.Product.Feature.UI;

public class SettingsViewModel {}
public class SettingsService {}
""".strip(),
        encoding="utf-8",
    )
    db = tmp_path / "feat2.db"
    run_index(tmp_path, db, sln=None, csproj=[proj], store_content=False, force=True)

    conn = connect(db, create=False)
    prow = conn.execute(
        "SELECT domain FROM projects WHERE path = ?", (str(proj.resolve()),)
    ).fetchone()
    assert prow is not None
    assert str(prow["domain"]) == "Acme"

    build_features(conn)
    conn.commit()
    frow = conn.execute(
        "SELECT domain FROM features WHERE name = ?", ("Settings",)
    ).fetchone()
    conn.close()
    assert frow is not None
    assert str(frow["domain"]) == "Acme"


def test_two_viewmodels_same_feature_name_same_project(tmp_path: Path) -> None:
    """UNIQUE(viewmodel): same stripped name + project must not abort inference."""
    proj = tmp_path / "Lib.csproj"
    proj.write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>', encoding="utf-8")
    (tmp_path / "One.cs").write_text(
        "namespace Billing.One;\npublic class ItemViewModel {}\n",
        encoding="utf-8",
    )
    (tmp_path / "Two.cs").write_text(
        "namespace Billing.Two;\npublic class ItemViewModel {}\n",
        encoding="utf-8",
    )
    db = tmp_path / "feat-dup.db"
    run_index(tmp_path, db, sln=None, csproj=[proj], store_content=False, force=True)

    conn = connect(db, create=False)
    n = build_features(conn)
    conn.commit()
    conn.close()
    assert n == 2

    conn = connect(db, create=False)
    qnames = {
        str(r[0])
        for r in conn.execute(
            "SELECT viewmodel FROM features WHERE name = ?", ("Item",)
        ).fetchall()
    }
    conn.close()
    assert qnames == {"Billing.One.ItemViewModel", "Billing.Two.ItemViewModel"}


def test_service_fallback_manager(tmp_path: Path) -> None:
    src = tmp_path / "M.cs"
    src.write_text(
        """
namespace X;

public class OrderViewModel {}
public class OrderManager {}
""".strip(),
        encoding="utf-8",
    )
    db = tmp_path / "feat3.db"
    run_index(tmp_path, db, sln=None, csproj=None, store_content=False, force=True)
    conn = connect(db, create=False)
    build_features(conn)
    conn.commit()
    row = conn.execute(
        "SELECT service FROM features WHERE name = ?", ("Order",)
    ).fetchone()
    conn.close()
    assert row is not None
    assert str(row["service"]) == "X.OrderManager"

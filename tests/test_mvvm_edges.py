from __future__ import annotations

from codeidx.db.connection import connect
from codeidx.indexer.pipeline import run_index
from codeidx.mvvm_edges import build_mvvm_edges


def test_mvvm_edges_view_and_primary_service(tmp_path) -> None:
    (tmp_path / "Mvvm.cs").write_text(
        """
namespace Demo.Mvvm;

public class OrderView {}

public class OrderViewModel
{
    public OrderViewModel(OrderClient client, OrderService service) { }
}

public class OrderClient { }

public class OrderService { }
""".strip(),
        encoding="utf-8",
    )
    db = tmp_path / "m.db"
    run_index(
        tmp_path,
        db,
        sln=None,
        csproj=None,
        store_content=False,
        force=True,
        index_mvvm_edges=True,
    )

    conn = connect(db, create=False)
    mv = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE edge_type = 'mvvm_view'"
    ).fetchone()
    ps = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE edge_type = 'mvvm_primary_service'"
    ).fetchone()
    row_v = conn.execute(
        """SELECT s1.qualified_name, s2.qualified_name FROM edges e
           JOIN symbols s1 ON s1.id = e.src_symbol_id
           JOIN symbols s2 ON s2.id = e.dst_symbol_id
           WHERE e.edge_type = 'mvvm_view'"""
    ).fetchone()
    row_p = conn.execute(
        """SELECT s1.qualified_name, s2.qualified_name FROM edges e
           JOIN symbols s1 ON s1.id = e.src_symbol_id
           JOIN symbols s2 ON s2.id = e.dst_symbol_id
           WHERE e.edge_type = 'mvvm_primary_service'"""
    ).fetchone()
    conn.close()

    assert int(mv[0]) == 1
    assert int(ps[0]) == 1
    assert row_v is not None
    assert str(row_v[0]) == "Demo.Mvvm.OrderView"
    assert str(row_v[1]) == "Demo.Mvvm.OrderViewModel"
    assert row_p is not None
    assert str(row_p[0]) == "Demo.Mvvm.OrderViewModel"
    assert str(row_p[1]) == "Demo.Mvvm.OrderService"


def test_mvvm_no_view_no_mvvm_view_edge(tmp_path) -> None:
    (tmp_path / "OnlyVm.cs").write_text(
        """
namespace Solo;

public class LoneViewModel
{
    public LoneViewModel(LoneService s) { }
}
public class LoneService { }
""".strip(),
        encoding="utf-8",
    )
    db = tmp_path / "solo.db"
    run_index(tmp_path, db, sln=None, csproj=None, force=True)

    conn = connect(db, create=False)
    n_view = int(
        conn.execute(
            "SELECT COUNT(*) FROM edges WHERE edge_type = 'mvvm_view'"
        ).fetchone()[0]
    )
    n_ps = int(
        conn.execute(
            "SELECT COUNT(*) FROM edges WHERE edge_type = 'mvvm_primary_service'"
        ).fetchone()[0]
    )
    conn.close()
    assert n_view == 0
    assert n_ps == 1


def test_run_index_no_mvvm_edges_flag(tmp_path) -> None:
    (tmp_path / "X.cs").write_text(
        """
namespace A;
public class VView {}
public class VViewModel { public VViewModel(VService s) {} }
public class VService {}
""".strip(),
        encoding="utf-8",
    )
    db = tmp_path / "off.db"
    run_index(tmp_path, db, sln=None, csproj=None, force=True, index_mvvm_edges=False)
    conn = connect(db, create=False)
    n = int(
        conn.execute(
            """SELECT COUNT(*) FROM edges WHERE edge_type IN
               ('mvvm_view','mvvm_primary_service')"""
        ).fetchone()[0]
    )
    conn.close()
    assert n == 0


def test_primary_service_prefers_service_over_client(tmp_path) -> None:
    """Deterministic: OrderService ranks before OrderClient."""
    (tmp_path / "P.cs").write_text(
        """
namespace P;

public class XView {}
public class XViewModel
{
    public XViewModel(OrderClient c, OrderService s) { }
}
public class OrderClient { }
public class OrderService { }
""".strip(),
        encoding="utf-8",
    )
    db = tmp_path / "prio.db"
    run_index(tmp_path, db, sln=None, csproj=None, force=True)
    conn = connect(db, create=False)
    row = conn.execute(
        """SELECT s2.qualified_name FROM edges e
           JOIN symbols s2 ON s2.id = e.dst_symbol_id
           WHERE e.edge_type = 'mvvm_primary_service'"""
    ).fetchone()
    conn.close()
    assert row is not None
    assert str(row[0]) == "P.OrderService"


def test_build_mvvm_edges_idempotent_delete_reinsert(tmp_path) -> None:
    (tmp_path / "R.cs").write_text(
        """
namespace R;
public class YView {}
public class YViewModel { public YViewModel(YSvc s) {} }
public class YSvc {}
""".strip(),
        encoding="utf-8",
    )
    db = tmp_path / "idemp.db"
    run_index(tmp_path, db, sln=None, csproj=None, force=True)
    conn = connect(db, create=False)
    n1 = int(conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0])
    build_mvvm_edges(conn, tmp_path)
    conn.commit()
    n2 = int(conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0])
    conn.close()
    assert n1 == n2

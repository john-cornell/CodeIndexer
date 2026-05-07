from __future__ import annotations


def _first_namespace_segment(qualified_name: str) -> str | None:
    if "." not in qualified_name:
        return None
    first = qualified_name.split(".", 1)[0].strip()
    return first or None


def _resolve_service(
    conn: sqlite3.Connection, base_qname: str
) -> str | None:
    for suffix in ("Service", "ServiceAgent", "Manager"):
        qn = base_qname + suffix
        row = conn.execute(
            """SELECT qualified_name FROM symbols
               WHERE kind IN ('type', 'interface') AND qualified_name = ?
               ORDER BY id LIMIT 1""",
            (qn,),
        ).fetchone()
        if row:
            return str(row[0])
    return None


def build_features(conn: sqlite3.Connection) -> int:
    conn.execute("SAVEPOINT codeidx_features")
    try:
        return _build_features_inner(conn)
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT codeidx_features")
        raise
    finally:
        conn.execute("RELEASE SAVEPOINT codeidx_features")


def _build_features_inner(conn: sqlite3.Connection) -> int:
    conn.execute("DELETE FROM features")
    rows = conn.execute(
        """SELECT s.name AS sym_name, s.qualified_name AS qname,
           (SELECT p.name FROM project_files pf
            JOIN projects p ON p.id = pf.project_id
            WHERE pf.file_id = s.file_id ORDER BY p.name LIMIT 1) AS project_name,
           (SELECT p.domain FROM project_files pf
            JOIN projects p ON p.id = pf.project_id
            WHERE pf.file_id = s.file_id ORDER BY p.name LIMIT 1) AS project_domain
           FROM symbols s
           WHERE s.kind = 'type' AND s.name LIKE '%ViewModel'"""
    ).fetchall()

    inserted = 0
    seen_viewmodel: set[str] = set()
    for row in rows:
        sym_name = str(row["sym_name"])
        qname = str(row["qname"])
        if qname in seen_viewmodel:
            continue
        seen_viewmodel.add(qname)
        project_name = row["project_name"]
        project_domain = row["project_domain"]

        feature_name = sym_name.removesuffix("ViewModel")
        if not feature_name:
            continue

        ns_prefix = qname.rsplit(".", 1)[0]
        base = f"{ns_prefix}.{feature_name}"

        domain: str | None = None
        if project_domain is not None:
            d = str(project_domain).strip()
            if d:
                domain = d
        if domain is None:
            domain = _first_namespace_segment(qname)

        proj = str(project_name) if project_name is not None else None
        service = _resolve_service(conn, base)

        conn.execute(
            """INSERT INTO features(name, domain, viewmodel, service, project)
               VALUES (?,?,?,?,?)""",
            (feature_name, domain, qname, service, proj),
        )
        inserted += 1

    return inserted

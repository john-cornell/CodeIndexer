from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from codeidx.db.connection import set_meta
from codeidx.storage import json_dumps

TOKEN_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
STOP_TERMS = {
    "get",
    "set",
    "service",
    "manager",
    "repository",
    "controller",
    "handler",
    "impl",
}
VERB_PREFIXES = ("validate", "persist", "notify", "create", "update", "delete", "sync")


@dataclass
class BuildResult:
    rows_written: int
    elapsed_ms: float


def _now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _index_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = 'index_version'").fetchone()
    if not row:
        return 0
    return int(str(row[0]))


def _set_layer_build(conn: sqlite3.Connection, layer: str, *, config_hash: str) -> None:
    conn.execute(
        """INSERT INTO layer_builds(layer, index_version, config_hash, built_at)
           VALUES(?,?,?,?)
           ON CONFLICT(layer) DO UPDATE SET
             index_version=excluded.index_version,
             config_hash=excluded.config_hash,
             built_at=excluded.built_at""",
        (layer, _index_version(conn), config_hash, _now_utc()),
    )


def _build_component_prompt(
    name: str, members: list[str], capabilities: list[str], top_terms: list[str]
) -> str:
    members_block = "\n".join(f"- {m}" for m in members[:12]) or "- (none)"
    caps_block = ", ".join(capabilities[:8]) or "(none)"
    terms_block = ", ".join(top_terms[:8]) or "(none)"
    return (
        "You are writing a concise coding-assistant component summary.\n"
        "Return exactly 1 sentence, factual, no marketing tone.\n"
        f"Component: {name}\n"
        f"Top terms: {terms_block}\n"
        f"Capabilities: {caps_block}\n"
        "Key members:\n"
        f"{members_block}\n"
    )


def _ollama_generate(*, model: str, prompt: str) -> str:
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    url = base_url.rstrip("/") + "/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ollama returned non-JSON response") from exc
    text = str(parsed.get("response") or "").strip()
    if not text:
        raise RuntimeError("Ollama returned empty response")
    return " ".join(text.split())


def build_semantic(conn: sqlite3.Connection) -> BuildResult:
    t0 = time.perf_counter()
    idx_version = _index_version(conn)
    conn.execute("DELETE FROM semantic_component_contracts")
    conn.execute("DELETE FROM semantic_contract_types")
    conn.execute("DELETE FROM semantic_flow_steps")
    conn.execute("DELETE FROM semantic_flows")
    conn.execute("DELETE FROM semantic_capability_evidence")
    conn.execute("DELETE FROM semantic_capabilities")
    conn.execute("DELETE FROM semantic_component_members")
    conn.execute("DELETE FROM semantic_components")

    rows = conn.execute(
        """SELECT s.id, s.name, s.kind, s.qualified_name, f.path, p.id
           FROM symbols s
           JOIN files f ON f.id = s.file_id
           LEFT JOIN project_files pf ON pf.file_id = f.id
           LEFT JOIN projects p ON p.id = pf.project_id"""
    ).fetchall()

    by_key: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        qn = str(r[3] or "")
        namespace = ".".join(qn.split(".")[:-1]) if "." in qn else ""
        proj = str(r[5]) if r[5] is not None else "none"
        key = f"{proj}:{namespace or 'global'}"
        by_key[key].append(r)

    component_id_by_symbol: dict[int, int] = {}
    components_written = 0
    for key in sorted(by_key):
        items = by_key[key]
        evid = sorted(int(r[0]) for r in items)
        name = key.split(":")[-1]
        conn.execute(
            """INSERT INTO semantic_components(key, name, primary_rule, source_kind, confidence, evidence_symbol_ids, index_version)
               VALUES(?,?,?,?,?,?,?)""",
            (
                key,
                name,
                "R-COMP-PROJECT-NAMESPACE",
                "extracted",
                min(1.0, 0.3 + (len(items) / 200.0)),
                json_dumps(evid),
                idx_version,
            ),
        )
        cid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        components_written += 1
        for r in items:
            sid = int(r[0])
            component_id_by_symbol[sid] = cid
            conn.execute(
                "INSERT INTO semantic_component_members(component_id, symbol_id, role, weight) VALUES(?,?,?,?)",
                (cid, sid, "member", 1.0),
            )

    _build_capabilities(conn, idx_version, component_id_by_symbol)
    _build_flows(conn, idx_version, component_id_by_symbol)
    _build_contracts(conn, idx_version, component_id_by_symbol)
    cfg_hash = hashlib.sha256(b"semantic-v1").hexdigest()
    _set_layer_build(conn, "semantic", config_hash=cfg_hash)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return BuildResult(rows_written=components_written, elapsed_ms=elapsed_ms)


def _tokenize(name: str) -> list[str]:
    fixed = name.replace("_", " ")
    out: list[str] = []
    for part in fixed.split():
        out.extend(TOKEN_RE.findall(part))
    return [t.lower() for t in out if t]


def _build_capabilities(
    conn: sqlite3.Connection, idx_version: int, component_id_by_symbol: dict[int, int]
) -> None:
    methods = conn.execute(
        "SELECT id, name FROM symbols WHERE kind IN ('method', 'function')"
    ).fetchall()
    grouped: dict[tuple[int, str], list[int]] = defaultdict(list)
    for row in methods:
        sid = int(row[0])
        cid = component_id_by_symbol.get(sid)
        if cid is None:
            continue
        tokens = _tokenize(str(row[1]))
        if not tokens:
            continue
        verb = tokens[0]
        if verb not in VERB_PREFIXES:
            continue
        obj = tokens[1] if len(tokens) > 1 else "item"
        phrase = f"{verb} {obj}"
        grouped[(cid, phrase)].append(sid)

    for (cid, phrase), symbol_ids in grouped.items():
        evid = sorted(symbol_ids)
        conf = min(1.0, 0.4 + len(evid) * 0.08)
        conn.execute(
            """INSERT INTO semantic_capabilities(component_id, phrase, source_kind, confidence, evidence_symbol_ids, index_version)
               VALUES(?,?,?,?,?,?)""",
            (cid, phrase, "extracted", conf, json_dumps(evid), idx_version),
        )
        cap_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        for sid in evid:
            conn.execute(
                "INSERT INTO semantic_capability_evidence(capability_id, method_symbol_id) VALUES(?,?)",
                (cap_id, sid),
            )


def _build_flows(
    conn: sqlite3.Connection, idx_version: int, component_id_by_symbol: dict[int, int]
) -> None:
    calls = conn.execute(
        "SELECT id, src_symbol_id, dst_symbol_id FROM edges WHERE edge_type = 'calls' AND src_symbol_id IS NOT NULL AND dst_symbol_id IS NOT NULL"
    ).fetchall()
    flow_by_entry: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
    for row in calls:
        eid = int(row[0])
        src = int(row[1])
        dst = int(row[2])
        src_c = component_id_by_symbol.get(src)
        dst_c = component_id_by_symbol.get(dst)
        if src_c is None or dst_c is None or src_c == dst_c:
            continue
        flow_by_entry[src].append((src_c, dst_c, eid))
    for entry_symbol_id, steps in flow_by_entry.items():
        path = "->".join(f"{a}:{b}" for a, b, _ in sorted(steps)[:8])
        evid = sorted({entry_symbol_id, *[s for _, _, s in steps]})
        conn.execute(
            """INSERT INTO semantic_flows(entry_symbol_id, path_signature, source_kind, confidence, evidence_symbol_ids, index_version)
               VALUES(?,?,?,?,?,?)""",
            (
                entry_symbol_id,
                path,
                "extracted",
                min(1.0, 0.3 + len(steps) * 0.1),
                json_dumps(evid),
                idx_version,
            ),
        )
        flow_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        for i, (from_c, to_c, edge_id) in enumerate(sorted(steps)[:8], start=1):
            conn.execute(
                """INSERT INTO semantic_flow_steps(flow_id, ord, from_component_id, to_component_id, edge_id)
                   VALUES(?,?,?,?,?)""",
                (flow_id, i, from_c, to_c, edge_id),
            )


def _build_contracts(
    conn: sqlite3.Connection, idx_version: int, component_id_by_symbol: dict[int, int]
) -> None:
    rows = conn.execute(
        """SELECT e.id, e.src_symbol_id, e.dst_symbol_id, ds.id, ds.kind
           FROM edges e
           JOIN symbols ds ON ds.id = e.dst_symbol_id
           WHERE e.edge_type IN ('calls', 'implements', 'inherits')
             AND e.src_symbol_id IS NOT NULL
             AND e.dst_symbol_id IS NOT NULL"""
    ).fetchall()
    seen_types: set[int] = set()
    for row in rows:
        edge_id = int(row[0])
        src = int(row[1])
        dst = int(row[2])
        type_symbol_id = int(row[3])
        kind = str(row[4] or "type")
        src_c = component_id_by_symbol.get(src)
        dst_c = component_id_by_symbol.get(dst)
        if src_c is None or dst_c is None or src_c == dst_c:
            continue
        if type_symbol_id not in seen_types:
            seen_types.add(type_symbol_id)
            conn.execute(
                """INSERT OR REPLACE INTO semantic_contract_types(type_symbol_id, kind, source_kind, confidence, evidence_symbol_ids, index_version)
                   VALUES(?,?,?,?,?,?)""",
                (
                    type_symbol_id,
                    kind,
                    "extracted",
                    0.6,
                    json_dumps([type_symbol_id]),
                    idx_version,
                ),
            )
        conn.execute(
            """INSERT OR IGNORE INTO semantic_component_contracts(component_id, type_symbol_id, direction, edge_id)
               VALUES(?,?,?,?)""",
            (src_c, type_symbol_id, "out", edge_id),
        )
        conn.execute(
            """INSERT OR IGNORE INTO semantic_component_contracts(component_id, type_symbol_id, direction, edge_id)
               VALUES(?,?,?,?)""",
            (dst_c, type_symbol_id, "in", edge_id),
        )


def build_conceptual(conn: sqlite3.Connection) -> BuildResult:
    t0 = time.perf_counter()
    idx_version = _index_version(conn)
    conn.execute("DELETE FROM conceptual_component_links")
    conn.execute("DELETE FROM conceptual_synonym_group_terms")
    conn.execute("DELETE FROM conceptual_synonym_groups")
    conn.execute("DELETE FROM conceptual_term_evidence")
    conn.execute("DELETE FROM conceptual_terms")

    rows = conn.execute(
        "SELECT id, name, kind, qualified_name FROM symbols"
    ).fetchall()
    token_to_symbols: dict[str, set[int]] = defaultdict(set)
    token_weights: Counter[str] = Counter()
    for row in rows:
        sid = int(row[0])
        name = str(row[1] or "")
        kind = str(row[2] or "")
        qn = str(row[3] or "")
        toks = _tokenize(name)
        ns_toks = _tokenize(qn.split(".")[0]) if "." in qn else []
        for t in toks + ns_toks:
            if len(t) < 3 or t in STOP_TERMS:
                continue
            token_to_symbols[t].add(sid)
            base = 1.5 if kind in ("type", "interface", "enum") else 1.0
            token_weights[t] += base

    term_id_by_token: dict[str, int] = {}
    for token in sorted(token_to_symbols):
        symbols = sorted(token_to_symbols[token])
        score = float(token_weights[token])
        conn.execute(
            """INSERT INTO conceptual_terms(term, normalized, score, source_kind, confidence, evidence_symbol_ids, index_version)
               VALUES(?,?,?,?,?,?,?)""",
            (
                token,
                token,
                score,
                "extracted",
                min(1.0, 0.3 + min(0.6, len(symbols) / 50.0)),
                json_dumps(symbols),
                idx_version,
            ),
        )
        term_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        term_id_by_token[token] = term_id
        for sid in symbols[:200]:
            conn.execute(
                "INSERT INTO conceptual_term_evidence(term_id, symbol_id, weight, channel) VALUES(?,?,?,?)",
                (term_id, sid, 1.0, "name"),
            )

    groups: dict[str, list[str]] = defaultdict(list)
    for token in sorted(term_id_by_token):
        root = token
        for suffix in ("service", "repository", "manager"):
            if token.endswith(suffix) and token != suffix:
                root = token[: -len(suffix)]
                break
        groups[root].append(token)

    for root in sorted(groups):
        terms = sorted(groups[root])
        rep_token = terms[0]
        rep_id = term_id_by_token[rep_token]
        evidence = sorted(
            {
                sid
                for token in terms
                for sid in token_to_symbols.get(token, set())
            }
        )
        conn.execute(
            """INSERT INTO conceptual_synonym_groups(representative_term_id, source_kind, confidence, evidence_symbol_ids, index_version)
               VALUES(?,?,?,?,?)""",
            (rep_id, "extracted", 0.5, json_dumps(evidence), idx_version),
        )
        gid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        for token in terms:
            conn.execute(
                """INSERT INTO conceptual_synonym_group_terms(group_id, term_id, link_rule)
                   VALUES(?,?,?)""",
                (gid, term_id_by_token[token], "R-SYN-SUFFIX"),
            )
        comp_scores = conn.execute(
            """SELECT scm.component_id, COUNT(*) AS c
               FROM semantic_component_members scm
               WHERE scm.symbol_id IN (
                 SELECT symbol_id FROM conceptual_term_evidence
                 WHERE term_id IN (
                   SELECT term_id FROM conceptual_synonym_group_terms WHERE group_id = ?
                 )
               )
               GROUP BY scm.component_id
               ORDER BY c DESC""",
            (gid,),
        ).fetchall()
        for row in comp_scores[:20]:
            conn.execute(
                """INSERT INTO conceptual_component_links(group_id, component_id, score, evidence_symbol_ids)
                   VALUES(?,?,?,?)""",
                (gid, int(row[0]), float(row[1]), json_dumps(evidence[:50])),
            )

    cfg_hash = hashlib.sha256(b"conceptual-v1").hexdigest()
    _set_layer_build(conn, "conceptual", config_hash=cfg_hash)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return BuildResult(rows_written=len(term_id_by_token), elapsed_ms=elapsed_ms)


def enrich_with_llm(
    conn: sqlite3.Connection,
    *,
    provider: str,
    model: str,
    prompt_version: str = "v1",
) -> BuildResult:
    t0 = time.perf_counter()
    if provider == "none":
        return BuildResult(rows_written=0, elapsed_ms=0.0)
    if provider not in ("ollama", "cloud"):
        raise ValueError(f"Unsupported provider: {provider}")
    if provider == "cloud":
        raise NotImplementedError(
            "Cloud provider wiring is not implemented yet. Use provider=ollama or provider=none."
        )
    rows = conn.execute(
        "SELECT id, name FROM semantic_components ORDER BY id LIMIT 500"
    ).fetchall()
    rows_written = 0
    for row in rows:
        cid = int(row[0])
        name = str(row[1] or "")
        members = [
            str(r[0])
            for r in conn.execute(
                """SELECT s.qualified_name
                   FROM semantic_component_members scm
                   JOIN symbols s ON s.id = scm.symbol_id
                   WHERE scm.component_id = ?
                   ORDER BY s.qualified_name
                   LIMIT 30""",
                (cid,),
            ).fetchall()
        ]
        capabilities = [
            str(r[0])
            for r in conn.execute(
                "SELECT phrase FROM semantic_capabilities WHERE component_id = ? ORDER BY confidence DESC, phrase LIMIT 20",
                (cid,),
            ).fetchall()
        ]
        top_terms = [
            str(r[0])
            for r in conn.execute(
                """SELECT ct.term
                   FROM conceptual_component_links ccl
                   JOIN conceptual_synonym_groups csg ON csg.id = ccl.group_id
                   JOIN conceptual_terms ct ON ct.id = csg.representative_term_id
                   WHERE ccl.component_id = ?
                   ORDER BY ccl.score DESC, ct.term
                   LIMIT 20""",
                (cid,),
            ).fetchall()
        ]
        prompt = _build_component_prompt(name, members, capabilities, top_terms)
        summary = _ollama_generate(model=model, prompt=prompt)
        conn.execute(
            "UPDATE semantic_components SET llm_summary = ?, llm_title = ? WHERE id = ?",
            (summary, name, cid),
        )
        input_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        conn.execute(
            """INSERT INTO enrichment_provenance(table_name, row_id, field_name, provider, model_id, prompt_version, input_hash, created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (
                "semantic_components",
                cid,
                "llm_summary",
                provider,
                model,
                prompt_version,
                input_hash,
                _now_utc(),
            ),
        )
        rows_written += 1
    cfg = {"provider": provider, "model": model, "prompt_version": prompt_version}
    _set_layer_build(conn, "enrichment", config_hash=hashlib.sha256(json.dumps(cfg, sort_keys=True).encode("utf-8")).hexdigest())
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return BuildResult(rows_written=rows_written, elapsed_ms=elapsed_ms)


def index_version_bump(conn: sqlite3.Connection) -> int:
    v = _index_version(conn) + 1
    set_meta(conn, "index_version", str(v))
    return v

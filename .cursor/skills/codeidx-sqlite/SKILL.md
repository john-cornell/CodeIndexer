---
name: codeidx-sqlite
description: >-
  Answers code-structure questions using the codeidx SQLite index (symbols,
  edges, FTS) via the configured SQLite MCP tools. Use when the user asks about
  references, callers, inheritance, symbols, file paths in the index, or
  navigation that should use structured queries instead of scanning the whole
  tree; or when exploring relationships in indexed C# code.
---

# codeidx SQLite index (MCP)

## Assumptions

- The **codeidx index** is already built (SQLite on disk).
- **SQLite MCP** is already configured in Cursor and points at that database.

Use the **MCP tools** the server exposes (e.g. `read_query`, `list_tables`, schema/description helpers—names vary by server) as the **primary** way to answer.

## Workflow

1. **Schema:** If needed, list tables or describe columns, then query.
2. **Structured questions:** Prefer **SQL** against core tables:
   - `symbols`, `edges`, `files`, `projects`, `project_edges`
   - FTS: `symbols_fts`, `files_fts` (and `file_contents_fts` if content was indexed)
3. **Edge types** include `calls`, `inherits`, `implements`, `imports`; `confidence` is `exact`, `heuristic`, or `unresolved`. Call resolution is mostly syntactic—treat **non-exact** confidence as exploratory, not proof of the resolved target.
4. For **callers** / **callees**, join `edges` (`edge_type = 'calls'`) with `symbols` and `files`. Qualify column names (`symbols.id`, `files.id`) when joining both tables.
5. **Interface implementers:** for interface symbol id `I`, query edges with `dst_symbol_id = I` and `symbols.kind = 'interface'`; include `edge_type IN ('implements','inherits')` only for legacy DBs. Prefer **`implements`** for C# interface implementation; **`inherits`** here means a resolved **class/struct** base (first in list), not “interface inheritance.” Use `edges.meta_json` (`base_resolved`, `dst_kind`, `base_kind_hint`) when `dst_symbol_id` is null. Indexing with a **solution** (`--sln`) resolves types across project references when the interface is in the same index.

Reserve **repo-wide grep** or reading dozens of files for cases the index cannot answer (non-indexed languages, comments-only search, etc.).

## Stale data

If results look wrong after large edits, suggest re-indexing: `python -m codeidx index .` from the repo root (or the indexed path), then re-query via MCP.

## Optional CLI fallback

If MCP is unavailable in a session, the same DB can be queried with **Python** (preferred on Windows; do not assume `sqlite3` is on PATH):

```bash
python -m codeidx query stats
python -m codeidx query find-symbol --name <Symbol>
python -m codeidx query path-search --substring <pathFragment>
python -m codeidx query callers-of --symbol-id <id>
python -m codeidx query implementations-of --symbol-id <id>
```

Default DB on Windows: `%LOCALAPPDATA%\codeidx\codeidx.db`. Use `--db` if the index lives elsewhere. An empty or wrong path produces an empty schema or a clear error—confirm with `stats` and the default path in the README.

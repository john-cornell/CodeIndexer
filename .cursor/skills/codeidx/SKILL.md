---
name: codeidx
description: >-
  Answers code-structure questions using the codeidx SQLite index (symbols,
  edges, FTS) via the configured SQLite MCP tools. Use when the user asks about
  references, callers, inheritance, symbols, file paths in the index, or
  navigation that should use structured queries instead of scanning the whole
  tree; or when exploring relationships in indexed C# code.
---

# codeidx index (MCP)

## Assumptions

- The **codeidx index** is already built (SQLite on disk).
- **SQLite MCP** is already configured in Cursor and points at that database.

Use the **MCP tools** the server exposes (e.g. `read_query`, `list_tables`, schema/description helpers—names vary by server) as the **primary** way to answer.

## Empty results — retry before giving up

If the first query, **`find-symbol`**, or FTS **`MATCH`** returns **nothing**, **do not stop**. Retry in order, keeping **`LIMIT`** small:

1. **Individual words from the target name**  
   Split compound identifiers: `AutoTimeService` → try `AutoTime`, `Service`, `Time`. Split `qualified_name` on `.` and search **`name`** or **`LIKE '%segment%'`** for **one segment at a time** (symbols table or `symbols_fts`).

2. **Similar / related words**  
   Try **synonyms or alternate role words** (e.g. *handler* / *consumer* / *processor*), **abbreviations** vs full words, and **casing** (`AutoTime` vs `Autotime`) with `LIKE` or case-insensitive patterns if your SQL layer supports it.

3. **Shorter needles**  
   Drop namespaces: match on **unqualified `name`** or the **last segment** of `qualified_name` only. Avoid matching the full `Ns.A.B.LongTypeName` in one go unless you know it is exact.

4. **Looser FTS**  
   Use **prefix** tokens where FTS5 allows (`term*`), **fewer quoted phrases**, or **one token per query** instead of a multi-word `MATCH` string.

5. **Path and file filters**  
   If you know a folder (e.g. `Services`, `Integrations`), constrain with **`files.path LIKE '%...%'`** and combine with a **broad symbol `name LIKE`**.

6. **Content grep last**  
   **`grep-text`** / `file_contents_fts` only if content was indexed (`--store-content`); use **short patterns** and retry with **single words**.

Stay bounded; iterate terms before falling back to wide repo grep or bulk file reads.

## Type symbols and incoming edges

**A type symbol often has no rows** where `dst_symbol_id = <that id>` (and none where `src_symbol_id = <that id>` except its own declaration edges). The index does **not** model every **mention** of a type (generic arguments, field types, `RegisterType<T>()`, DI, etc.)—only **`calls`**, **base-list** `inherits`/`implements`, and **`imports`**.

For **“who uses this type”**, use **`symbols_fts`**, bounded **`LIKE`** on `name`/`qualified_name`, path filters, and **`grep-text`** if content was indexed. Do not treat empty **`find-references`** as proof the type is unused.

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

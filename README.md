# CodeIndexer (`codeidx`)

**CodeIndexer** is a small CLI that indexes C# codebases into a **SQLite** database: symbols, FTS search, call/inheritance edges, and MSBuild project references. It is built for **local tooling and AI assistants** (Cursor MCP, custom scripts) that need structured queries instead of rescanning the tree on every question.

The Python package name is **`codeidx`**.

---

## What you get

| Capability | Notes |
|------------|--------|
| **Symbols** | Types, methods, interfaces, etc., with `qualified_name` and file locations |
| **Edges** | `calls`, `injects`, `implements` / `inherits` (C# bases), `imports` (usings); optional `string_ref` (`--index-string-literals`); heuristic **`mvvm_view`** / **`mvvm_primary_service`** (on by default; `--no-mvvm-edges` to skip) |
| **FTS5** | Symbol and file-path search |
| **Projects** | `.sln` / `.csproj` graph: project references and package references |
| **Incremental index** | Skips unchanged files by size, mtime, and SHA-256 |

**Not** a Roslyn replacement: resolution is **syntactic** (Tree-sitter), with documented heuristics. See [docs/TRADEOFFS.md](docs/TRADEOFFS.md).

---

## Requirements

- **Python 3.10+**
- **Windows, macOS, or Linux** (default index DB is **per repository** under `.codeidx/db/`)

---

## Install

Clone this repo (the **indexer tool**—not the application you want to index):

```bash
cd CodeIndexer
pip install -e .
```

With dev dependencies (tests):

```bash
pip install -e ".[dev]"
```

Use a virtual environment if you do not want a system-wide install. Installing registers the **`codeidx`** command and `python -m codeidx`.

---

## Quick start

### 1. Index from your solution root

```powershell
cd C:\path\to\your\repo
python -m codeidx index
```

- If you **omit the path**, the current directory is used (equivalent to `index .`).
- Pass **`--sln`** to pin a solution when several `.sln` files exist or when the `.sln` lives above your working folder.

```powershell
python -m codeidx index --sln "C:\path\to\YourSolution.sln"
```

- If the tree contains **many** solutions and you want **one** full index with a **merged** project graph (instead of a weaker file-only pass), use **`--all-solutions`** (non-interactive):

```powershell
python -m codeidx index "C:\path\to\monorepo" --all-solutions --force
```

### 2. Confirm where the database is

Without **`--db`**, the index is stored at **`<repo>/.codeidx/db/codeidx.db`** (relative to the directory you passed to **`index`**, usually the repo root). After indexing:

```powershell
python -m codeidx query stats
```

This prints the resolved file path, size, row counts, and metadata—use it to align **Cursor MCP**, scripts, and the CLI on the **same** `.db` file.

### 3. Query from the CLI (no `sqlite3` required)

On Windows, prefer **`python -m codeidx query …`** rather than assuming `sqlite3` is on `PATH`.

```powershell
python -m codeidx query find-symbol --name MyType
python -m codeidx query implementations-of --symbol-id 42
python -m codeidx query callers-of --symbol-id 99
python -m codeidx query obsidian --out-dir .codeidx/vault
python -m codeidx notes get-or-create My.Namespace.Service
python -m codeidx scan-obsidian --all-solutions --force --index-string-literals --out-dir .codeidx/vault
```

---

## Default database location

| Context | Default path |
|---------|----------------|
| **Repository root** `REPO` | `REPO/.codeidx/db/codeidx.db` |

Override for both **index** and **query**:

```bash
python -m codeidx index /path/to/repo --db ./my-index.db
python -m codeidx query --db ./my-index.db stats
```

Group options like **`--db`** go **before** the subcommand: `python -m codeidx query --db D:\idx.db find-symbol --name Foo`.

---

## `index` command

```text
python -m codeidx index [REPO] [options]
```

| Option | Meaning |
|--------|--------|
| `REPO` | Root folder to scan (optional; default: current directory) |
| `--db PATH` | SQLite file to create/update |
| `--sln PATH` | Solution file for MSBuild project graph and multi-project resolution |
| `--csproj PATH` | Repeatable; explicit `.csproj` roots (if no `--sln`, one may be chosen interactively) |
| `--force` | Re-parse **all** `.cs` files even if unchanged (use after upgrading the tool or when you need a full graph refresh) |
| `--all-solutions` | Discover **every** `.sln` under `REPO`, **merge** all referenced projects (de-duplicated) into one MSBuild graph, then index. Use for monorepos with many solutions: stronger cross-project resolution than `--no-sln` and no per-solution loop. Incompatible with `--no-sln`, `--sln`, and `--csproj`. |
| `--no-sln` | Skip `.sln` / `.csproj` discovery and **any interactive prompt**; index all files under `REPO` without a solution graph (faster, weaker resolution). Incompatible with `--sln` / `--csproj` and with `--all-solutions`. |
| `--no-progress` | Suppress periodic **stderr** progress lines (default: a line every 200 `.cs` files or every 8 seconds). |
| `--index-string-literals` | Emit **`string_ref`** edges when a quoted literal uniquely matches a type/interface/enum/delegate **name** (heuristic; see TRADEOFFS). |
| `--no-mvvm-edges` | Skip post-index **`mvvm_view`** / **`mvvm_primary_service`** edges (default: emit). |
| `--store-content` | Store raw file text for `grep-text` / `file_contents_fts` (larger DB) |
| `--ignore PATTERN` | Extra gitignore-style ignore (repeatable) |

**Incremental behavior:** unchanged files (same size, mtime, hash) are **skipped**. If you see `files_parsed: 0` and expected updates, run with **`--force`** or delete the DB and re-index.

If both **`--sln`** and **`--csproj`** are passed, the solution wins for the project graph (a note is printed).

### Re-indexing and full refresh

- **Update the same DB in place** by default: each run overwrites or refreshes data for **changed** files. You do not need a new database path unless you want a separate index.
- **Full re-parse (reindex everything):** add **`--force`**. Use after **upgrading `codeidx`**, when the graph looks **stale** after big refactors, or when **incremental** runs skipped files you know changed.
- **Many `.sln` files under one root** (e.g. a monorepo): use **`--all-solutions --force`** for one merged project graph and a full pass; see [Quick start](#quick-start) above. Avoid bare `index` on a huge tree with many solutions (interactive pick or long stall); use **`--all-solutions`**, a single explicit **`--sln`**, or **`--no-sln`** for file-only (weaker resolution).
- **Progress:** by default, **`index`** prints periodic lines to **stderr** (every **200** files or **8** seconds). Use **`--no-progress`** for quiet logs (e.g. **CI**).
- **Confirm:** `python -m codeidx query stats` after a run; expect updated row counts and `meta` such as `last_index_ms` when the write finished.

---

## `query` subcommands

All use the same default DB as **`index`** unless **`--db`** is set.

| Subcommand | Purpose |
|------------|--------|
| `stats` | DB path, size, row counts, `meta` (sanity check for tooling) |
| `find-symbol` | Lookup by `--name`, optional `--kind`, `--file-glob` |
| `find-references` | Indexed **edges whose `dst_symbol_id` is this symbol** (`--symbol-id` or `--qualified`)—**not** full IDE “find all references” (see [TRADEOFFS](docs/TRADEOFFS.md#type-symbols-and-find-references)) |
| `callers-of` | Call edges to `--symbol-id` |
| `implementations-of` | Types implementing an **interface** symbol id |
| `path-search` | Files whose path contains a substring |
| `grep-text` | Substring or `--regex` over stored content (needs `--store-content` when indexing) |
| `obsidian` | Generate Obsidian markdown vault from indexed symbols/edges |

## `notes` subcommands

Persistent symbol notes live in `.codeidx/notes` by default, with a protected `## Notes` section.

| Subcommand | Purpose |
|------------|--------|
| `get-or-create` | Create or return note for `symbol_name`, with DB-derived structure section |
| `append` | Append text under the protected `## Notes` heading (after `get-or-create`) |
| `sync` | Rebuild structural top half from DB and preserve the `## Notes` section |

Examples:

```bash
python -m codeidx notes get-or-create My.Namespace.Worker
python -m codeidx notes append My.Namespace.Worker --text "Design note: …"
python -m codeidx notes sync My.Namespace.Worker --db ./my-index.db
```

Run **`notes`** from the **repository root** (or pass **`--repo`**) so the default DB and `.codeidx/notes/` paths resolve correctly.

## Obsidian export

### `scan-obsidian` (index + vault)

Runs **`index`** on **`REPO`** (default: current directory), then generates the vault. Same indexing flags as **`index`** where applicable: **`--all-solutions`**, **`--force`**, **`--index-string-literals`**, **`--store-content`**, **`--no-mvvm-edges`**, **`--no-progress`**, **`--sln`** / **`--csproj`** (same combination rules as **`index`**). **`--out-dir`** overrides the vault path (default **`<repo>/.codeidx/vault`**). On Windows, use **`scan.bat`** / **`full_scan.bat`** / **`update_scan.bat`** / **`full_update_scan.bat`** from this repo — [docs/CHEATSHEET.md](docs/CHEATSHEET.md).

### Commands

- Export only (assumes you already indexed):

```bash
python -m codeidx query obsidian --out-dir .codeidx/vault
```

- One-shot scan + export (typical: merged solutions + string literals + full parse):

```bash
python -m codeidx scan-obsidian --all-solutions --force --index-string-literals --out-dir .codeidx/vault
```

- Same with stored file bodies (larger DB, enables **`grep-text`**):

```bash
python -m codeidx scan-obsidian --all-solutions --force --index-string-literals --store-content --out-dir .codeidx/vault
```

### Output shape

`query obsidian` creates one markdown file per indexed type-like symbol (`type`, `interface`, `enum`, `delegate`) under the output directory, nested by namespace path.

Generated pages include wiki-links for:

- inheritance (`inherits` / `implements`)
- constructor dependencies (`injects`)
- methods
- called methods (`calls`)

If you use Windows batch helpers (in this repo), see **`scan.bat`**, **`full_scan.bat`**, **`update_scan.bat`**, **`full_update_scan.bat`** — [docs/CHEATSHEET.md](docs/CHEATSHEET.md) (Index section).

**`find-references` vs “every use of this type”:** The index only records certain relationships (calls, inheritance bases, usings). Types used in generics, DI registration, field types, etc. often have **no** incoming graph edges—use partial **`find-symbol`**, **`symbols_fts` / `LIKE`**, or **`grep-text`** for that. Details: [docs/TRADEOFFS.md](docs/TRADEOFFS.md#type-symbols-and-find-references).

Example:

```bash
python -m codeidx query find-symbol --name IWorker --kind interface --limit 20
```

Raw SQL examples: [docs/example_queries.sql](docs/example_queries.sql).

---

## MCP, Cursor, and AI workflows

- Point the **codeidx MCP** server at the **same DB** as **`query stats`** (default **`<repo>/.codeidx/db/codeidx.db`**). **`init-agents`** writes **`mcp`** with **`--repo`** and **`--db`**; SQL tools are read-only; note tools write **`.codeidx/notes/*.md`**.
- An empty or wrong path can look like a “broken” index (no tables or zero-byte file). **`query stats`** from the repo root is the fastest check.
- Optional **Agent Skills** live under **`.cursor/skills/codeidx/`** after **`init-agents`**; keep **`--db`** (and **`--repo`**) in MCP aligned with how you **`index`**.

---

## C#: `implements` vs `inherits`

- **`implements`** is used for **interface** implementation (including `class C : IThing` when `IThing` resolves or matches the usual `I`+PascalCase hint).
- **`inherits`** is used for a resolved **non-interface** base on the **first** base-list entry when appropriate.

Cross-project types (e.g. interface in a referenced project) are resolved when indexing with a **solution** and documented rules. Details and **`meta_json`** fields: [docs/TRADEOFFS.md](docs/TRADEOFFS.md).

---

## Troubleshooting

| Symptom | What to check |
|---------|----------------|
| `Missing argument 'REPO'` | Use **`python -m codeidx index`** with no args from the repo root, or **`index .`**, or upgrade to a version where `REPO` defaults to `.`. |
| `files_parsed: 0`, all skipped | Expected if nothing changed; use **`--force`** to re-parse. |
| MCP shows empty schema | Wrong DB path in MCP; confirm with **`query stats`** from the repo root (default **`.codeidx/db/codeidx.db`**). |
| “No implementations” for an interface | Re-index with **`--sln`** covering the project that declares the interface; see TRADEOFFS. |
| **`find-references` empty for a type** | Normal if nothing in the indexed edge set points at that symbol (no calls/callees resolved to it, no base list). Use substring search / FTS / `grep-text`; see [TRADEOFFS](docs/TRADEOFFS.md#type-symbols-and-find-references). |

---

## Documentation

| Doc | Content |
|-----|--------|
| [docs/CHEATSHEET.md](docs/CHEATSHEET.md) | Short commands, defaults, **validation** checklist |
| [docs/AGENTS_AND_HOOKS.md](docs/AGENTS_AND_HOOKS.md) | Cursor MCP, Claude hooks, WSL vs Windows |
| [docs/TRADEOFFS.md](docs/TRADEOFFS.md) | Precision, inheritance edges, **type symbols vs find-references**, incremental behavior, limitations |
| [docs/example_queries.sql](docs/example_queries.sql) | Sample SQL (FTS, edges, joins) |

---

## Development

```bash
pytest
```

---

## Repository

**GitHub:** [github.com/john-cornell/CodeIndexer](https://github.com/john-cornell/CodeIndexer)  

Package / CLI name: **`codeidx`**.

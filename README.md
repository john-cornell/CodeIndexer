# CodeIndexer (`codeidx`)

**CodeIndexer** is a small CLI that indexes C# codebases into a **SQLite** database: symbols, FTS search, call/inheritance edges, and MSBuild project references. It is built for **local tooling and AI assistants** (Cursor MCP, custom scripts) that need structured queries instead of rescanning the tree on every question.

The Python package name is **`codeidx`**.

---

## What you get

| Capability | Notes |
|------------|--------|
| **Symbols** | Types, methods, interfaces, etc., with `qualified_name` and file locations |
| **Edges** | `calls`, `implements` / `inherits` (C# bases), `imports` (usings) |
| **FTS5** | Symbol and file-path search |
| **Projects** | `.sln` / `.csproj` graph: project references and package references |
| **Incremental index** | Skips unchanged files by size, mtime, and SHA-256 |

**Not** a Roslyn replacement: resolution is **syntactic** (Tree-sitter), with documented heuristics. See [docs/TRADEOFFS.md](docs/TRADEOFFS.md).

---

## Requirements

- **Python 3.10+**
- **Windows, macOS, or Linux** (paths and default DB location differ by OS)

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

### 2. Confirm where the database is

Without **`--db`**, the index is stored in a **per-user default path** (see table below). After indexing:

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
```

---

## Default database location

| OS | Default path |
|----|----------------|
| **Windows** | `%LOCALAPPDATA%\codeidx\codeidx.db` (e.g. `C:\Users\<you>\AppData\Local\codeidx\codeidx.db`) |
| **macOS** | `~/Library/Application Support/codeidx/codeidx.db` |
| **Linux** | `~/.local/share/codeidx/codeidx.db` |

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
| `--no-sln` | Skip `.sln` / `.csproj` discovery and **any interactive prompt**; index all files under `REPO` without a solution graph (use when many solutions exist or for batch scripts). Incompatible with `--sln` / `--csproj`. |
| `--store-content` | Store raw file text for `grep-text` (larger DB) |
| `--ignore PATTERN` | Extra gitignore-style ignore (repeatable) |

**Incremental behavior:** unchanged files (same size, mtime, hash) are **skipped**. If you see `files_parsed: 0` and expected updates, run with **`--force`** or delete the DB and re-index.

If both **`--sln`** and **`--csproj`** are passed, the solution wins for the project graph (a note is printed).

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

**`find-references` vs “every use of this type”:** The index only records certain relationships (calls, inheritance bases, usings). Types used in generics, DI registration, field types, etc. often have **no** incoming graph edges—use partial **`find-symbol`**, **`symbols_fts` / `LIKE`**, or **`grep-text`** for that. Details: [docs/TRADEOFFS.md](docs/TRADEOFFS.md#type-symbols-and-find-references).

Example:

```bash
python -m codeidx query find-symbol --name IWorker --kind interface --limit 20
```

Raw SQL examples: [docs/example_queries.sql](docs/example_queries.sql).

---

## MCP, Cursor, and AI workflows

- Point your **SQLite MCP** server (or any client) at the **same path** printed by **`query stats`** or listed in the table above.
- An empty or wrong path can look like a “broken” index (no tables or zero-byte file). **`query stats`** and the default path documentation are the fastest checks.
- Optional **Agent Skills** for structured queries can live in `.cursor/skills/` in this repo; configure MCP **`--db-path`** to match your indexer output.

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
| MCP shows empty schema | Wrong **`--db-path`**; confirm with **`query stats`** and `%LOCALAPPDATA%\codeidx\codeidx.db` on Windows. |
| “No implementations” for an interface | Re-index with **`--sln`** covering the project that declares the interface; see TRADEOFFS. |
| **`find-references` empty for a type** | Normal if nothing in the indexed edge set points at that symbol (no calls/callees resolved to it, no base list). Use substring search / FTS / `grep-text`; see [TRADEOFFS](docs/TRADEOFFS.md#type-symbols-and-find-references). |

---

## Documentation

| Doc | Content |
|-----|--------|
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

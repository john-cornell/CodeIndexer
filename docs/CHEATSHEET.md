# codeidx cheat sheet

Short reference. Install **`codeidx`** separately on **Windows** and **WSL** (different Pythons).

---

## Defaults (from repo root)

| What | Path |
|------|------|
| Index DB | `<repo>/.codeidx/db/codeidx.db` |
| Symbol notes | `<repo>/.codeidx/notes/*.md` |
| Obsidian export | `<repo>/.codeidx/vault/` |

Override any time with `--db` or `--repo`.

---

## Install (each environment)

```bash
pip install -e /path/to/CodeIndexer    # or pipx / venv on WSL
pip install -e C:\path\to\CodeIndexer  # Windows
```

```bash
codeidx --help
```

---

## Index

```bash
cd /path/to/your/repo
python -m codeidx index --all-solutions --force
python -m codeidx index --sln path/to/Solution.sln
python -m codeidx scan-obsidian --all-solutions --force   # index + vault
```

Heuristic **`mvvm_view`** / **`mvvm_primary_service`** edges run **by default** after indexing. Opt out: **`--no-mvvm-edges`**. (String literal **`string_ref`** edges stay opt-in: **`--index-string-literals`**.)

Windows helper (from CodeIndexer repo): `scan_full.bat` forwards `--all-solutions --force` plus your args.

---

## Query

```bash
python -m codeidx query stats
python -m codeidx query find-symbol --name SomeType
python -m codeidx query obsidian --out-dir .codeidx/vault
```

---

## Symbol notes (markdown, not .cs)

```bash
codeidx notes get-or-create My.Namespace.MyType
codeidx notes append My.Namespace.MyType --text "…"
codeidx notes sync My.Namespace.MyType
```

---

## Cursor + Claude Code

From **your app repo root**:

```bash
codeidx init-agents                    # cursor + claude (default)
codeidx init-agents --agent cursor
codeidx init-agents --agent claude
codeidx init-agents --force-mcp       # replace conflicting MCP entry
codeidx init-agents --force           # overwrite bundled skill copy in .cursor
```

- **Cursor:** restart IDE after `mcp.json` changes.
- **Claude Code:** hooks in `.claude/settings.local.json`; project hints in `CLAUDE.md` (see [AGENTS_AND_HOOKS.md](AGENTS_AND_HOOKS.md)).

**codeidx MCP** tools: `read_query`, `list_tables`, `describe_table` only (read-only).

---

## Validation (quick)

Run from **your indexed repo root**.

| Step | Command / check |
|------|------------------|
| 1. CLI works | `codeidx --help` exits 0 |
| 2. DB exists | `test -f .codeidx/db/codeidx.db` (or `Test-Path .codeidx\db\codeidx.db` on Windows) |
| 3. DB readable | `python -m codeidx query stats` shows path + row counts |
| 4. Cursor MCP | `.cursor/mcp.json` contains server with `--db` … `codeidx.db` |
| 5. Claude hooks | `grep -q 'hook pre-grep-glob' .claude/settings.local.json` |
| 6. Claude context | `grep -q 'codeidx init-agents' CLAUDE.md` (after `init-agents --agent claude`) |

If **stats** fails: run **`index`** again from that repo root (or pass **`--db`** consistently).

---

## More detail

- [AGENTS_AND_HOOKS.md](AGENTS_AND_HOOKS.md) — Cursor vs Claude, WSL paths, hooks
- [TRADEOFFS.md](TRADEOFFS.md) — indexer limits
- [README.md](../README.md) — full CLI tables

# Agents, hooks, and `init-agents`

This document describes how **codeidx** integrates with **Cursor** and **Claude Code**, what **`codeidx init-agents`** does, and how to run it on **Windows** and **WSL**.

## Quick start

From the **root of the project you want to configure** (e.g. your app repo, not necessarily this indexer repo):

```bash
codeidx init-agents /path/to/your/repo --db /path/to/codeidx.db
```

Omit the repo argument only if your **current working directory** is already that root:

```bash
cd /path/to/your/repo
codeidx init-agents
```

Then:

- **Cursor:** restart the IDE after `.cursor/mcp.json` changes.
- **Claude Code:** new sessions pick up **`.claude/settings.local.json`** (hooks + **`mcpServers`**); restart or reload MCP after changes. Use **`/hooks`** to inspect hook definitions.

## What `init-agents` does

### CLI overview

| Option | Purpose |
|--------|---------|
| `[REPO]` | Project root to receive files. Default: current directory (`.`). |
| `--db PATH` | SQLite DB used in MCP config and in Claude **SessionStart** hook. Default: OS-specific (see below). |
| `--agent cursor\|claude\|all` | Repeatable; default `all`. |
| `--mcp-name NAME` | MCP server key in **Cursor** `mcp.json` and **Claude** `mcpServers`. Default: `codeidx`. |
| `--dry-run` | Print planned actions; do not write files. |
| `--force` | Overwrite Cursor skill + `schema.sql` even if unchanged. |
| `--force-mcp` | Replace existing MCP definition when it differs (same `--mcp-name`; applies to Cursor and Claude). |

### Cursor (`--agent cursor` or `all`)

Writes under **`REPO/.cursor/`**:

1. **`skills/codeidx/SKILL.md`** — bundled agent skill (schema reference points at `./schema.sql` next to it).
2. **`skills/codeidx/schema.sql`** — copy of the indexer schema for offline reference.
3. **`mcp.json`** — merges an **`mcpServers`** entry (default name `codeidx`) that runs:

   `python -m codeidx mcp --repo <REPO> --db <resolved --db>`

   (or the `codeidx` executable from your install, depending on environment). The server exposes read-only SQL plus note tools that write **`<repo>/.codeidx/notes/*.md`**.

**Not configured by `init-agents`:** Cursor’s native **`.cursor/hooks.json`** (different product feature). This command sets up **MCP + skill**, not Cursor hook scripts.

**Two MCP concepts:** The **codeidx** stdio server (SQL + note tools) is what **`init-agents`** registers. A separate **generic SQLite** MCP (e.g. `user-sqlite`) only exposes ad-hoc SQL — it does **not** include **`get_or_create_note`** / **`append_note`** unless that server is custom-built to do so.

### Claude Code (`--agent claude` or `all`)

Merges **`REPO/.claude/settings.local.json`** (creates it if missing):

1. **Hooks** — same **PreToolUse** / **PostToolUse** / **SessionStart** groups as documented below (idempotent by command marker).
2. **`mcpServers`** — merges the same **stdio** definition as Cursor (`python -m codeidx mcp --repo <REPO> --db <db>`), keyed by **`--mcp-name`** (default `codeidx`). **`--force-mcp`** overwrites an existing entry with a different definition.

Also merges a short **codeidx** section into **`REPO/CLAUDE.md`** (between HTML comment markers) so **Claude Code** sessions (including `/resume`) load hook and notes facts from the project root — not only from searching `~/.claude`.

| Event | Matcher / filter | Command |
|-------|------------------|---------|
| **PreToolUse** | `Grep\|Glob` | `codeidx hook pre-grep-glob` (or `python -m codeidx …` if no `codeidx` on `PATH`) |
| **PostToolUse** | `Edit\|Write` with **`if`:** `Edit(*.cs)\|Write(*.cs)` | `codeidx hook post-cs-edit` |
| **SessionStart** | `startup\|resume\|clear\|compact` | `codeidx hook session-start --db … --repo …` |

**SessionStart** compares the DB file mtime to **`git log -1`** in **`--repo`**; if the index looks older than the last commit, it injects a reminder to re-index. If the DB file is missing, it injects a “run `codeidx index`” style message.

**Upgrade behavior:** If `codeidx` is on `PATH` but an existing hook still uses **`python … -m codeidx hook`**, the next `init-agents` run **rewrites** that command to the **`codeidx`** shim (helps **pipx** / WSL where system `python3` might be a different/old install).

### Global vs project (Claude Code)

- **User/global:** e.g. `~/.claude/settings.json` — applies everywhere.
- **Project:** `REPO/.claude/settings.local.json` — applies when the project is loaded.

Both apply together. Your global **PreToolUse** hooks (e.g. a Bash rewriter) and project **codeidx** hooks can all run; they are not mutually exclusive.

### Manual / global Claude MCP (optional)

**`init-agents`** writes the **codeidx** server into **project** **`settings.local.json`**. For a **user-wide** MCP list, or to use **`python3`** / a **`codeidx`** shim path instead of **`python`**, merge **`mcpServers`** into **`~/.claude/settings.json`** or use **`claude mcp add`** ([Claude Code MCP docs](https://code.claude.com/docs/en/agent-sdk/mcp)). On **WSL**, run **`init-agents` from WSL** so embedded paths are **`/mnt/c/...`** if that is how you index.

## Default database path (`--db` omitted)

Resolved relative to the **repository root** (the path you pass to **`init-agents`**, or the current directory for CLI defaults):

| Context | Default file |
|---------|----------------|
| **Index / query / MCP** | `<repo>/.codeidx/db/codeidx.db` |

There is **no** global per-user default. Use **`--db PATH`** everywhere if you store the SQLite file elsewhere.

**WSL:** A repo on **`C:\...`** is the same tree as **`/mnt/c/...`**. Run **`init-agents`** and **`index`** in the environment whose paths you want embedded (Windows vs WSL); use the same resolved **`--db`** if you override the default.

## Windows vs WSL vs “same repo”

- Repos on **`C:\...`** are the same files as **`/mnt/c/...`** in WSL. One `init-agents` run updates that tree; both environments see the same `.cursor` and `.claude` files.
- **`codeidx` must be installed per environment** (Windows Python vs WSL pipx/venv are separate).
- Hook commands embed **`--db`** and **`--repo`** as resolved when you ran **`init-agents`**. If you only use **WSL** Claude against that repo, run **`init-agents` in WSL** with **`/mnt/c/...`** paths so subprocesses and git see consistent paths.

## Supporting commands

### `codeidx mcp`

Stdio MCP server: **read-only** SQL (`read_query`, `list_tables`, `describe_table`) on the index DB, plus **`get_or_create_note`**, **`append_note`**, **`sync_note_structure`** for symbol markdown under **`.codeidx/notes/`**. Pass **`--repo`** (indexed project root) and **`--db`** so paths resolve correctly. Cursor should use the same **`--db`** you **`index`**.

### `codeidx hook …`

Used only as **Claude Code** command hooks; stdin is hook JSON, stdout is hook result JSON.

- **`pre-grep-glob`** — nudge toward codeidx / FTS before heavy Grep/Glob.
- **`post-cs-edit`** — reminder about knowledge notes after C# edits.
- **`session-start`** — staleness / missing DB messaging; requires **`--db`** and **`--repo`**.

## Common messages from `init-agents`

| Message | Meaning |
|---------|---------|
| **Unchanged … SKILL.md / schema.sql** | Content matches bundled template; use **`--force`** to overwrite. |
| **Skipped MCP server … use --force-mcp** | Cursor `mcp.json` or Claude **`mcpServers`** already has that server name with a **different** definition. |
| **Hook already present** | Idempotent skip (or marker matched). |
| **Refreshed hook …** | Old `python -m codeidx hook` upgraded to `codeidx` on `PATH`. |

## Install notes (especially WSL)

- **PEP 668** (externally managed Python): use a **venv** or **pipx** instead of `pip install --global` on Debian/Ubuntu.
- **`codeidx --help`** should list **`init-agents`**, **`mcp`**, and **`hook`**. If **`python3 -m codeidx`** shows only **`index`** / **`query`**, that interpreter has an **old** `codeidx`; use **`which codeidx`** (pipx) or fix the install.
- After **pipx** issues, ensure **`~/.local/bin/codeidx`** is a valid shim (`pipx reinstall codeidx`).

## Verifying in Claude Code

- Run **`/hooks`** in the Claude Code UI to see merged hooks and their source files.
- Project file: **`REPO/.claude/settings.local.json`**.

## Related repo paths

| Path | Role |
|------|------|
| `src/codeidx/cli/init_agents_cmd.py` | `init-agents` Click command |
| `src/codeidx/agents/cursor_setup.py` | Cursor skill + `mcp.json` merge |
| `src/codeidx/agents/mcp_spec.py` | Shared stdio MCP spec for Cursor + Claude |
| `src/codeidx/agents/claude_setup.py` | Claude `settings.local.json` merge (hooks + `mcpServers`) + hook command building |
| `src/codeidx/cli/hook_cmd.py` | `codeidx hook` implementations |
| `src/codeidx/cli/mcp_cmd.py` | `codeidx mcp` entry |
| `src/codeidx/agents/bundled/cursor/SKILL.md` | Bundled Cursor skill source |

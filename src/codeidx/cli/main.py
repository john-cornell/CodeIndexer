from __future__ import annotations

import sys
import time
from pathlib import Path

import click

from codeidx import notes
from codeidx.cli import obsidian, query_cmd
from codeidx.cli.hook_cmd import hook_group
from codeidx.cli.init_agents_cmd import register_init_agents
from codeidx.cli.mcp_cmd import mcp_cmd
from codeidx.indexer.pipeline import IndexStats, run_index
from codeidx.paths import (
    repo_vault_dir,
    resolve_db_path,
    require_existing_db,
)
from codeidx.projects.msbuild import discover_csproj_files, discover_solution_files


def _pick_from_list(items: list[Path], label: str) -> Path | None:
    if not items:
        return None
    if len(items) == 1:
        return items[0]
    click.echo(f"Multiple {label} found:")
    for i, p in enumerate(items, start=1):
        click.echo(f"  {i}) {p}")
    choice = click.prompt("Enter number", type=click.IntRange(1, len(items)))
    return items[choice - 1]


@click.group()
@click.version_option()
def main() -> None:
    """Code intelligence indexer backed by SQLite."""


register_init_agents(main)
main.add_command(mcp_cmd)
main.add_command(hook_group)


@main.command("index")
@click.argument(
    "repo",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=False,
)
@click.option(
    "--db",
    "db_path",
    type=click.Path(path_type=Path),
    default=None,
    help="SQLite database (default: <REPO>/.codeidx/db/codeidx.db).",
)
@click.option("--sln", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None)
@click.option(
    "--csproj",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Repeatable. Explicit csproj roots to associate.",
)
@click.option(
    "--store-content",
    is_flag=True,
    help="Store raw file text for substring grep (larger DB).",
)
@click.option(
    "--ignore",
    "extra_ignores",
    multiple=True,
    help="Extra gitignore-style patterns.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Re-parse every file even when size/mtime/hash match (full refresh).",
)
@click.option(
    "--all-solutions",
    "all_solutions",
    is_flag=True,
    help="Load every .sln under REPO, merge all projects (deduplicated) into one graph, then index (stronger than --no-sln for monorepos). Incompatible with --no-sln, --sln, and --csproj.",
)
@click.option(
    "--no-sln",
    "no_sln",
    is_flag=True,
    help="Skip .sln/.csproj discovery and any interactive prompt; index files only (weaker cross-project symbol resolution).",
)
@click.option(
    "--index-string-literals",
    "index_string_literals",
    is_flag=True,
    help="Emit string_ref edges when a quoted literal matches exactly one type/interface/enum/delegate name (heuristic).",
)
@click.option(
    "--no-mvvm-edges",
    "no_mvvm_edges",
    is_flag=True,
    help="Skip heuristic mvvm_view / mvvm_primary_service edges (default: emit after index).",
)
@click.option(
    "--no-progress",
    "no_progress",
    is_flag=True,
    help="Do not print periodic progress to stderr (default: show: every 200 .cs files or every 8s).",
)
def index_cmd(
    repo: Path | None,
    db_path: Path | None,
    sln: Path | None,
    csproj: tuple[Path, ...],
    store_content: bool,
    extra_ignores: tuple[str, ...],
    force: bool,
    all_solutions: bool,
    no_sln: bool,
    index_string_literals: bool,
    no_mvvm_edges: bool,
    no_progress: bool,
) -> None:
    """Scan REPO and update DB. If REPO is omitted, uses the current directory."""
    root = (repo or Path(".")).resolve()
    db_resolved = resolve_db_path(root, db_path)
    if db_path is None:
        click.echo(f"Using database: {db_resolved}", err=True)
    sln_path = sln.resolve() if sln else None
    csproj_list = [p.resolve() for p in csproj] if csproj else None
    if all_solutions and (no_sln or sln_path is not None or csproj_list):
        click.echo(
            "Error: --all-solutions cannot be combined with --no-sln, --sln, or --csproj.",
            err=True,
        )
        sys.exit(2)

    if no_sln and (sln_path is not None or csproj_list):
        click.echo("Error: --no-sln cannot be combined with --sln or --csproj.", err=True)
        sys.exit(2)

    if sln_path is not None and csproj_list:
        click.echo(
            "Note: --sln is set; explicit --csproj entries are ignored for project graph.",
            err=True,
        )

    if no_sln:
        sln_path = None
        csproj_list = None
    elif not all_solutions and sln_path is None and not csproj_list:
        slns = discover_solution_files(root)
        csps = discover_csproj_files(root)
        if len(slns) >= 1:
            sln_path = _pick_from_list(slns, ".sln files")
        elif len(csps) >= 1:
            chosen = _pick_from_list(csps, ".csproj files")
            csproj_list = [chosen] if chosen else None

    if all_solutions:
        n = len(discover_solution_files(root))
        click.echo(f"Merged {n} solution file(s) under {root} (--all-solutions).", err=True)

    progress_t0 = time.perf_counter()
    if not no_progress:
        click.echo("Indexing .cs files (progress every 200 files or 8s)…", err=True)

    def _on_progress(s: IndexStats) -> None:
        elapsed = time.perf_counter() - progress_t0
        click.echo(
            f"  ... progress: scanned={s.files_scanned}  parsed={s.files_parsed}  "
            f"skipped_unchanged={s.files_skipped_unchanged}  errors={len(s.errors)}  "
            f"elapsed_s={elapsed:.0f}",
            err=True,
        )

    stats = run_index(
        root,
        db_resolved,
        sln=sln_path,
        csproj=list(csproj_list) if csproj_list else None,
        all_solutions=all_solutions,
        store_content=store_content,
        extra_ignore=list(extra_ignores) if extra_ignores else None,
        force=force,
        index_string_literals=index_string_literals,
        index_mvvm_edges=not no_mvvm_edges,
        progress_callback=None if no_progress else _on_progress,
    )
    click.echo("Index complete.")
    click.echo(f"  files_scanned:          {stats.files_scanned}")
    click.echo(f"  files_skipped_unchanged:{stats.files_skipped_unchanged}")
    click.echo(f"  files_parsed:           {stats.files_parsed}")
    click.echo(f"  symbols_written:        {stats.symbols_written}")
    click.echo(f"  edges_written:          {stats.edges_written}")
    click.echo(f"  bytes_read:             {stats.bytes_read}")
    click.echo(f"  elapsed_ms:             {stats.elapsed_ms:.1f}")
    for err in stats.errors:
        click.echo(f"  error: {err}", err=True)


@main.group("query")
@click.option(
    "--repo",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Repository root (default: current directory). Implies --db under .codeidx/db/.",
)
@click.option(
    "--db",
    "db_path",
    type=click.Path(path_type=Path),
    default=None,
    help="SQLite database (default: <repo>/.codeidx/db/codeidx.db).",
)
@click.pass_context
def query_group(ctx: click.Context, repo: Path | None, db_path: Path | None) -> None:
    ctx.ensure_object(dict)
    repo_root = (repo or Path(".")).resolve()
    db_resolved = resolve_db_path(repo_root, db_path)
    require_existing_db(db_resolved)
    if db_path is None:
        click.echo(f"Using database: {db_resolved}", err=True)
    ctx.obj["db"] = db_resolved
    ctx.obj["repo_root"] = repo_root


@query_group.command("find-symbol")
@click.option("--name", default=None)
@click.option("--kind", default=None)
@click.option("--file-glob", "file_glob", default=None)
@click.option("--limit", default=100, type=int)
@click.pass_context
def q_find_symbol(
    ctx: click.Context,
    name: str | None,
    kind: str | None,
    file_glob: str | None,
    limit: int,
) -> None:
    db_path: Path = ctx.obj["db"]
    rows = query_cmd.cmd_find_symbol(
        db_path, name=name, kind=kind, file_glob=file_glob, limit=limit
    )
    for r in rows:
        click.echo(
            f"{r['id']}\t{r['kind']}\t{r['qualified_name']}\t{r['path']}:{r['span_start_line']}"
        )


@query_group.command(
    "find-references",
    help=(
        "List edges where dst_symbol_id matches the symbol (indexed calls, bases, etc.). "
        "Not full IDE 'find all references' for types; see docs/TRADEOFFS.md."
    ),
)
@click.option("--symbol-id", "symbol_id", type=int, default=None)
@click.option("--qualified", default=None)
@click.option("--limit", default=200, type=int)
@click.pass_context
def q_find_references(
    ctx: click.Context,
    symbol_id: int | None,
    qualified: str | None,
    limit: int,
) -> None:
    db_path: Path = ctx.obj["db"]
    rows = query_cmd.cmd_find_references(
        db_path, symbol_id=symbol_id, qualified=qualified, limit=limit
    )
    if not rows and qualified and symbol_id is None:
        click.echo("No symbol resolved; try --symbol-id.", err=True)
        sys.exit(2)
    for r in rows:
        click.echo(
            f"{r['path']}:{r['ref_start_line']}\t{r['edge_type']}\t{r['confidence']}"
        )


@query_group.command("callers-of")
@click.option("--symbol-id", type=int, required=True)
@click.option("--limit", default=200, type=int)
@click.pass_context
def q_callers_of(ctx: click.Context, symbol_id: int, limit: int) -> None:
    db_path: Path = ctx.obj["db"]
    rows = query_cmd.cmd_callers_of(db_path, symbol_id=symbol_id, limit=limit)
    for r in rows:
        src = r["src_q"] or ""
        click.echo(f"{r['path']}:{r['ref_start_line']}\t{r['confidence']}\t{src}")


@query_group.command("implementations-of")
@click.option("--symbol-id", type=int, required=True)
@click.option("--limit", default=200, type=int)
@click.pass_context
def q_impl_of(ctx: click.Context, symbol_id: int, limit: int) -> None:
    db_path: Path = ctx.obj["db"]
    rows = query_cmd.cmd_implementations_of(db_path, symbol_id=symbol_id, limit=limit)
    for r in rows:
        click.echo(f"{r['qualified_name']}\t{r['path']}:{r['span_start_line']}")


@query_group.command("features")
@click.option("--name", default=None)
@click.option("--limit", default=500, type=int)
@click.pass_context
def q_features(ctx: click.Context, name: str | None, limit: int) -> None:
    db_path: Path = ctx.obj["db"]
    rows = query_cmd.cmd_features(db_path, name=name, limit=limit)
    for r in rows:
        dom = r["domain"] or ""
        svc = r["service"] or ""
        proj = r["project"] or ""
        click.echo(
            f"{r['id']}\t{r['name']}\t{dom}\t{r['viewmodel']}\t{svc}\t{proj}"
        )


@query_group.command("path-search")
@click.option("--substring", required=True)
@click.option("--limit", default=200, type=int)
@click.pass_context
def q_path_search(ctx: click.Context, substring: str, limit: int) -> None:
    db_path: Path = ctx.obj["db"]
    rows = query_cmd.cmd_path_search(db_path, substring=substring, limit=limit)
    for r in rows:
        click.echo(f"{r['id']}\t{r['path']}")


@query_group.command("stats")
@click.pass_context
def q_stats(ctx: click.Context) -> None:
    """Print database path, size, row counts, and meta (sanity check for tooling)."""
    db_path: Path = ctx.obj["db"]
    info = query_cmd.cmd_index_stats(db_path)
    click.echo(f"db_path:      {info['db_path']}")
    click.echo(f"size_bytes:   {info['size_bytes']}")
    counts = info["counts"]
    assert isinstance(counts, dict)
    for k in ("files", "symbols", "edges", "projects", "features"):
        click.echo(f"count_{k}: {counts.get(k, 0)}")
    meta = info["meta"]
    assert isinstance(meta, dict)
    if meta:
        click.echo("meta:")
        for mk, mv in meta.items():
            click.echo(f"  {mk}: {mv}")
    else:
        click.echo("meta: (empty)")


@query_group.command("grep-text")
@click.option("--pattern", required=True)
@click.option("--regex", "use_regex", is_flag=True)
@click.option("--limit", default=100, type=int)
@click.pass_context
def q_grep_text(
    ctx: click.Context,
    pattern: str,
    use_regex: bool,
    limit: int,
) -> None:
    db_path: Path = ctx.obj["db"]
    rows = query_cmd.cmd_grep_text(
        db_path, pattern=pattern, limit=limit, use_regex=use_regex
    )
    if not rows:
        click.echo(
            "No matches. Use --store-content when indexing for text grep, or try --regex.",
            err=True,
        )
    for path, snip in rows:
        click.echo(f"{path}\t{snip}")


@query_group.command("obsidian")
@click.option(
    "--out-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory (default: <repo>/.codeidx/vault).",
)
@click.pass_context
def q_obsidian(ctx: click.Context, out_dir: Path | None) -> None:
    db_path: Path = ctx.obj["db"]
    repo_root: Path = ctx.obj["repo_root"]
    out = (out_dir or repo_vault_dir(repo_root)).resolve()
    count = obsidian.generate_vault(db_path, out)
    click.echo(f"Generated {count} Obsidian notes in {out}")


@main.group("notes")
@click.option(
    "--repo",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Repository root (default: current directory). Notes live under .codeidx/notes/.",
)
@click.option(
    "--notes-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Override notes directory (default: <repo>/.codeidx/notes).",
)
@click.pass_context
def notes_group(ctx: click.Context, repo: Path | None, notes_dir: Path | None) -> None:
    ctx.ensure_object(dict)
    repo_root = (repo or Path(".")).resolve()
    ctx.obj["repo_root"] = repo_root
    ctx.obj["notes_dir"] = notes_dir.resolve() if notes_dir else None


@notes_group.command("get-or-create")
@click.argument("symbol_name")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
@click.pass_context
def notes_get_or_create(
    ctx: click.Context, symbol_name: str, db_path: Path | None
) -> None:
    repo_root: Path = ctx.obj["repo_root"]
    ndir = ctx.obj["notes_dir"]
    db_resolved = resolve_db_path(repo_root, db_path)
    require_existing_db(db_resolved)
    note_path, _text = notes.get_or_create_note(
        repo_root, db_resolved, symbol_name, notes_dir=ndir
    )
    click.echo(str(note_path))


@notes_group.command("append")
@click.argument("symbol_name")
@click.option("--text", "text_opt", default=None, help="Text to append under ## Notes")
@click.option(
    "--from-stdin",
    "from_stdin",
    is_flag=True,
    help="Read append text from stdin (use when content has newlines).",
)
@click.pass_context
def notes_append(
    ctx: click.Context,
    symbol_name: str,
    text_opt: str | None,
    from_stdin: bool,
) -> None:
    repo_root: Path = ctx.obj["repo_root"]
    ndir = ctx.obj["notes_dir"]
    if from_stdin:
        text = sys.stdin.read()
    elif text_opt is not None:
        text = text_opt
    else:
        raise click.UsageError("Provide --text or --from-stdin.")
    note_path = notes.append_to_notes_section(
        repo_root, symbol_name, text, notes_dir=ndir
    )
    click.echo(str(note_path))


@notes_group.command("sync")
@click.argument("symbol_name")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
@click.pass_context
def notes_sync(ctx: click.Context, symbol_name: str, db_path: Path | None) -> None:
    repo_root: Path = ctx.obj["repo_root"]
    ndir = ctx.obj["notes_dir"]
    db_resolved = resolve_db_path(repo_root, db_path)
    require_existing_db(db_resolved)
    note_path = notes.sync_note_structure(
        repo_root, db_resolved, symbol_name, notes_dir=ndir
    )
    click.echo(str(note_path))


@main.command("scan-obsidian")
@click.argument(
    "repo",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=False,
)
@click.option(
    "--db",
    "db_path",
    type=click.Path(path_type=Path),
    default=None,
    help="SQLite database (default: <REPO>/.codeidx/db/codeidx.db).",
)
@click.option("--sln", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None)
@click.option(
    "--csproj",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Repeatable. Explicit csproj roots to associate.",
)
@click.option(
    "--all-solutions",
    "all_solutions",
    is_flag=True,
    help="Load every .sln under REPO and merge all projects into one graph.",
)
@click.option(
    "--no-sln",
    "no_sln",
    is_flag=True,
    help="Skip .sln/.csproj discovery and any prompt; index files only.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Re-parse every file even when unchanged (full refresh).",
)
@click.option(
    "--index-string-literals",
    "index_string_literals",
    is_flag=True,
    help="Emit string_ref edges for unique type-like string literals.",
)
@click.option(
    "--no-mvvm-edges",
    "no_mvvm_edges",
    is_flag=True,
    help="Skip heuristic mvvm_view / mvvm_primary_service edges (default: emit after index).",
)
@click.option(
    "--no-progress",
    "no_progress",
    is_flag=True,
    help="Do not print periodic progress lines while indexing.",
)
@click.option(
    "--out-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Obsidian vault directory (default: <REPO>/.codeidx/vault).",
)
def scan_obsidian_cmd(
    repo: Path | None,
    db_path: Path | None,
    sln: Path | None,
    csproj: tuple[Path, ...],
    all_solutions: bool,
    no_sln: bool,
    force: bool,
    index_string_literals: bool,
    no_mvvm_edges: bool,
    no_progress: bool,
    out_dir: Path | None,
) -> None:
    """Index and export Obsidian vault in one command."""
    root = (repo or Path(".")).resolve()
    db_resolved = resolve_db_path(root, db_path)
    if db_path is None:
        click.echo(f"Using database: {db_resolved}", err=True)
    sln_path = sln.resolve() if sln else None
    csproj_list = [p.resolve() for p in csproj] if csproj else None
    if all_solutions and (no_sln or sln_path is not None or csproj_list):
        click.echo(
            "Error: --all-solutions cannot be combined with --no-sln, --sln, or --csproj.",
            err=True,
        )
        sys.exit(2)
    if no_sln and (sln_path is not None or csproj_list):
        click.echo("Error: --no-sln cannot be combined with --sln or --csproj.", err=True)
        sys.exit(2)
    if sln_path is not None and csproj_list:
        click.echo(
            "Note: --sln is set; explicit --csproj entries are ignored for project graph.",
            err=True,
        )
    if no_sln:
        sln_path = None
        csproj_list = None
    elif not all_solutions and sln_path is None and not csproj_list:
        slns = discover_solution_files(root)
        csps = discover_csproj_files(root)
        if len(slns) >= 1:
            sln_path = _pick_from_list(slns, ".sln files")
        elif len(csps) >= 1:
            chosen = _pick_from_list(csps, ".csproj files")
            csproj_list = [chosen] if chosen else None
    if all_solutions:
        n = len(discover_solution_files(root))
        click.echo(f"Merged {n} solution file(s) under {root} (--all-solutions).", err=True)
    progress_t0 = time.perf_counter()
    if not no_progress:
        click.echo("Indexing .cs files (progress every 200 files or 8s)...", err=True)

    def _on_progress(s: IndexStats) -> None:
        elapsed = time.perf_counter() - progress_t0
        click.echo(
            f"  ... progress: scanned={s.files_scanned}  parsed={s.files_parsed}  "
            f"skipped_unchanged={s.files_skipped_unchanged}  errors={len(s.errors)}  "
            f"elapsed_s={elapsed:.0f}",
            err=True,
        )

    stats = run_index(
        root,
        db_resolved,
        sln=sln_path,
        csproj=list(csproj_list) if csproj_list else None,
        all_solutions=all_solutions,
        store_content=False,
        extra_ignore=None,
        force=force,
        index_string_literals=index_string_literals,
        index_mvvm_edges=not no_mvvm_edges,
        progress_callback=None if no_progress else _on_progress,
    )
    click.echo("Index complete.")
    click.echo(f"  files_scanned:          {stats.files_scanned}")
    click.echo(f"  files_skipped_unchanged:{stats.files_skipped_unchanged}")
    click.echo(f"  files_parsed:           {stats.files_parsed}")
    click.echo(f"  symbols_written:        {stats.symbols_written}")
    click.echo(f"  edges_written:          {stats.edges_written}")
    click.echo(f"  bytes_read:             {stats.bytes_read}")
    click.echo(f"  elapsed_ms:             {stats.elapsed_ms:.1f}")
    for err in stats.errors:
        click.echo(f"  error: {err}", err=True)

    out = (out_dir or repo_vault_dir(root)).resolve()
    count = obsidian.generate_vault(db_resolved, out)
    click.echo(f"Generated {count} Obsidian notes in {out}")


if __name__ == "__main__":
    main()

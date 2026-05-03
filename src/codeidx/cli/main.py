from __future__ import annotations

import sys
import time
from pathlib import Path

import click

from codeidx.cli import query_cmd
from codeidx.indexer.pipeline import IndexStats, run_index
from codeidx.paths import default_db_path
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
    help=f"SQLite database file (default: {default_db_path()})",
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
    no_progress: bool,
) -> None:
    """Scan REPO and update DB. If REPO is omitted, uses the current directory."""
    db_resolved = (db_path or default_db_path()).resolve()
    if db_path is None:
        click.echo(f"Using default database: {db_resolved}", err=True)
    root = (repo or Path(".")).resolve()
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
    "--db",
    "db_path",
    type=click.Path(path_type=Path),
    default=None,
    help=f"SQLite database file (default: {default_db_path()})",
)
@click.pass_context
def query_group(ctx: click.Context, db_path: Path | None) -> None:
    ctx.ensure_object(dict)
    db_resolved = (db_path or default_db_path()).resolve()
    if not db_resolved.is_file():
        click.echo(
            f"Database not found: {db_resolved}\n"
            "Run `codeidx index` (or pass --db) to create it.",
            err=True,
        )
        sys.exit(1)
    if db_path is None:
        click.echo(f"Using default database: {db_resolved}", err=True)
    ctx.obj["db"] = db_resolved


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
    for k in ("files", "symbols", "edges", "projects"):
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


if __name__ == "__main__":
    main()

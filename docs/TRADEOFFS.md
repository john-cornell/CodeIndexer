# Tradeoffs and limitations (codeidx v1)

## Precision model

- **Exact**: Same qualified name match in SQLite, or a single unambiguous symbol match in scope.
- **Heuristic**: Multiple candidates share a simple name; the indexer picks a best-effort row (often first match in project scope).
- **Unresolved**: No symbol row was linked (unknown callee, external BCL types, or failed match).

Cross-file resolution does **not** use Roslyn or MSBuild semantics. Tree-sitter provides **syntactic** structure only.

## Inheritance vs implements (C#)

### Meaning of `edge_type`

- **`implements`**: the base type is (or is treated as) an **interface**—including `class C : IThing` where `IThing` is an interface. This matches IDE wording (“implements”) rather than OO “inherits from class.”
- **`inherits`**: the base type resolved to a **class/struct/record** symbol (`kind` is not `interface`), and this entry was the **first** base in the list (`base_index` 0 in `meta_json`). Further bases that are interfaces are stored as **`implements`**.

If resolution fails but the simple name matches the C# convention **`I` + uppercase** (e.g. `IIntegrationTarget`), the edge is still stored as **`implements`** so consumers are not misled into reading “class inheritance.”

### Resolution scope

When indexing with a **solution** (via `--sln` or explicit `--csproj` list), symbol lookup for base types uses the **union of all `.cs` files linked to any project in that solution**, not only the current file’s project. That allows `IIntegrationTarget` defined in a referenced project to resolve to `dst_symbol_id` for a type in another project.

Without a project graph, lookup falls back to **global** name search (limited rows), same as v0 behavior.

If multiple interfaces share the same short name in the index, resolution may stay **`unresolved`** until disambiguation is improved.

### End-of-run repair

After every index pass, edges with `dst_symbol_id IS NULL` for base-list rows are **tried again** against the full set of indexed files. That removes ordering effects (e.g. App project indexed before Lib) so cross-project interfaces can still link on the first full index.

### `meta_json` on base-list edges (guaranteed / optional)

Always present after indexing for C# base list edges:

| Field | Meaning |
|-------|---------|
| `base_text` | Raw type text from the source (from Tree-sitter). |
| `base_index` | 0 = first base in the list, 1 = second, … |
| `base_short` | Simple name after stripping generics/namespaces (e.g. `IIntegrationTarget`). |
| `base_resolved` | `true` if `dst_symbol_id` was set, else `false`. |
| `base_kind_hint` | If unresolved: `interface` when the `I+Uppercase` heuristic applies, else `unknown`. |
| `dst_kind` | If resolved: symbol `kind` of the destination (`interface`, `type`, …). |

External-only or ambiguous bases may remain unresolved; consumers should not treat `inherits` as “definitely a class” without checking `dst_kind` or `implements`.

## Type symbols and `find-references`

The CLI’s **`find-references`** (and SQL `WHERE dst_symbol_id = ?` on `edges`) lists **only rows the indexer actually emitted** with that destination symbol. v1 emits **`calls`**, **`injects`** (constructor parameter type edges), **`inherits` / `implements`** (C# **base list** only), **`imports`**, and optionally **`string_ref`** when **`--index-string-literals`** was used at index time.

**Most uses of a type name are not edges:** generic arguments (`RegisterType<MyEntity>()`), field/property types, `typeof(T)`, attributes, and DI wiring usually **do not** create an `edges` row pointing at the type’s symbol id (except the narrow **`string_ref`** case above). A type symbol can therefore have **zero** incoming edges even when the type is heavily used—this is expected, not a missing “generic inheritance” row.

For **“who references this type”** in the broad sense, combine:

- **`symbols_fts`** / `symbols` with **`LIKE '%PartialName%'`** (bounded `LIMIT`) when the exact short name is unknown;
- **`query find-symbol`** with a substring or path filter;
- **`grep-text`** (requires **`--store-content`** when indexing) for text occurrences.

A future indexer could add broader **`type_ref`**-style edges from more type-mention sites; until then, grep/FTS complement the graph.

## Constructor injection edges (`injects`)

When parsing C# constructors, the indexer emits `edge_type = 'injects'` from the enclosing class symbol to each constructor parameter type.

- `src_symbol_id`: class symbol id (when class symbol resolves in the same file pass).
- `dst_symbol_id`: resolved parameter type symbol id when available in indexed scope.
- `confidence`: `exact` / `heuristic` / `unresolved`, using the same symbol lookup model as other non-import edge types.
- `meta_json`: includes `parameter_name` and `parameter_index`.

This is syntactic constructor-parameter extraction, not a semantic DI container model (it does not prove runtime registration/lifetime or service activation path).

## String literals (`string_ref`, optional)

When **`--index-string-literals`** is passed to **`index`**, the C# walker records **`string_ref`** candidates from ordinary **`"..."`** literals (not interpolated `$"..."` in v1). A row is **only emitted** when:

- The inner text looks like a **PascalCase-like** identifier (length ≥ 4, first character uppercase, alphanumeric + underscore); and  
- The index contains **exactly one** symbol with that **`name`** and `kind IN ('type','interface','enum','delegate')`.

Otherwise the candidate is dropped (no unresolved `string_ref` row). This can link e.g. `"MyEntity"` in a string to the `MyEntity` type symbol when the name is unique in the index—**not** a semantic “reference” like Roslyn; duplicates or `enum_member` names are intentionally excluded from the destination filter.

Per file, at most **256** string candidates are considered (budget shared with the walker). **`find-references`** on a type will include **`string_ref`** edges when present.

## Incremental indexing

A file is skipped when **size**, **mtime**, and **sha256** match the last index. If you copy files preserving timestamps incorrectly, or hash collisions (theoretical), you could skip needed work—prefer a full re-index after bulk restores. After upgrading the indexer or when you need all symbols/edges recomputed, use `python -m codeidx index --force` (same DB path) or delete the database and index again.

## Stale cross-file edges

When file **A** changes and removes a symbol, edges stored under other files **B** that pointed to that symbol get `dst_symbol_id` set to NULL (FK) or remain until **B** is reindexed. A full pass or future “impacted files” analysis would fix this; v1 documents the gap.

## Full-text search

- **Path FTS** is always updated for `files.path`.
- **Symbol FTS** indexes `name` and `qualified_name`.
- **Content grep** requires `--store-content` during indexing (duplicates source text in SQLite). Without it, `grep-text` falls back to `files.content` (NULL) and returns no matches unless you re-index with the flag.

## Scale

Large repositories: parsing is CPU-bound; SQLite writes are batched per file. Extremely parallel indexing may contend on the DB writer—reduce parallelism in a future version if needed.

## Language coverage

v1 ships a **C#** Tree-sitter handler. Other languages require new handlers implementing the same `LanguageHandler` contract.

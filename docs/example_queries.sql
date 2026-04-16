-- Example SQL against a codeidx database
-- Adjust paths and ids for your run.

-- All symbols in a file path
SELECT s.id, s.kind, s.qualified_name, s.span_start_line, s.span_end_line
FROM symbols s
JOIN files f ON f.id = s.file_id
WHERE f.path LIKE '%MyService.cs%'
ORDER BY s.span_start_line;

-- Incoming call edges to a symbol id (e.g. 42)
SELECT f.path, e.ref_start_line, e.confidence, e.edge_type
FROM edges e
JOIN files f ON f.id = e.src_file_id
WHERE e.dst_symbol_id = 42 AND e.edge_type = 'calls'
ORDER BY f.path, e.ref_start_line;

-- Types implementing an interface symbol id (dst must be the interface row)
SELECT s.qualified_name, f.path, s.span_start_line
FROM edges e
JOIN symbols s ON s.id = e.src_symbol_id
JOIN symbols d ON d.id = e.dst_symbol_id
JOIN files f ON f.id = s.file_id
WHERE e.dst_symbol_id = 99
  AND d.kind = 'interface'
  AND e.edge_type IN ('implements', 'inherits');

-- Project dependency graph
SELECT p1.path AS src, p2.path AS dst, pe.edge_kind, pe.target
FROM project_edges pe
JOIN projects p1 ON p1.id = pe.src_project_id
LEFT JOIN projects p2 ON p2.id = pe.dst_project_id
ORDER BY p1.path;

-- FTS: symbol name search (FTS5 syntax)
SELECT s.id, s.qualified_name, f.path
FROM symbols_fts sf
JOIN symbols s ON s.id = sf.rowid
JOIN files f ON f.id = s.file_id
WHERE symbols_fts MATCH 'Run*'
LIMIT 50;

-- FTS: file path search
SELECT f.id, f.path
FROM files_fts ff
JOIN files f ON f.id = ff.rowid
WHERE files_fts MATCH 'Services'
LIMIT 50;

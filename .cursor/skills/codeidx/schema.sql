-- Core schema for codeidx v1
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY NOT NULL,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS folders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  path TEXT NOT NULL UNIQUE,
  parent_id INTEGER REFERENCES folders(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  path TEXT NOT NULL UNIQUE,
  folder_id INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
  size INTEGER NOT NULL DEFAULT 0,
  mtime_ns INTEGER NOT NULL DEFAULT 0,
  sha256 TEXT NOT NULL DEFAULT '',
  language TEXT NOT NULL DEFAULT '',
  last_indexed_at TEXT NOT NULL DEFAULT '',
  content TEXT
);

CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  path TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  domain TEXT
);

CREATE TABLE IF NOT EXISTS project_files (
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  PRIMARY KEY (project_id, file_id)
);

CREATE TABLE IF NOT EXISTS project_edges (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  src_project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  dst_project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
  edge_kind TEXT NOT NULL,
  target TEXT,
  UNIQUE (src_project_id, dst_project_id, edge_kind, target)
);

CREATE TABLE IF NOT EXISTS symbols (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  qualified_name TEXT NOT NULL DEFAULT '',
  span_start_line INTEGER NOT NULL,
  span_end_line INTEGER NOT NULL,
  span_start_col INTEGER NOT NULL DEFAULT 0,
  span_end_col INTEGER NOT NULL DEFAULT 0,
  ts_node_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_id);
CREATE INDEX IF NOT EXISTS idx_symbols_qname ON symbols(qualified_name);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);

CREATE TABLE IF NOT EXISTS edges (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  src_symbol_id INTEGER REFERENCES symbols(id) ON DELETE SET NULL,
  dst_symbol_id INTEGER REFERENCES symbols(id) ON DELETE SET NULL,
  src_file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  dst_file_id INTEGER REFERENCES files(id) ON DELETE SET NULL,
  edge_type TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'unresolved',
  ref_start_line INTEGER,
  ref_start_col INTEGER,
  ref_end_line INTEGER,
  ref_end_col INTEGER,
  meta_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_edges_src_file ON edges(src_file_id);
CREATE INDEX IF NOT EXISTS idx_edges_dst_sym ON edges(dst_symbol_id);
CREATE INDEX IF NOT EXISTS idx_edges_src_sym ON edges(src_symbol_id);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type);

CREATE TABLE IF NOT EXISTS features (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  domain TEXT,
  viewmodel TEXT NOT NULL,
  service TEXT,
  project TEXT,
  UNIQUE (viewmodel)
);

CREATE INDEX IF NOT EXISTS idx_features_name ON features(name);
CREATE INDEX IF NOT EXISTS idx_features_project ON features(project);

-- FTS5: file paths
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
  path,
  content='files',
  content_rowid='id',
  tokenize = 'unicode61'
);

CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
  INSERT INTO files_fts(rowid, path) VALUES (new.id, new.path);
END;
CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
  INSERT INTO files_fts(files_fts, rowid, path) VALUES('delete', old.id, old.path);
END;
CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
  INSERT INTO files_fts(files_fts, rowid, path) VALUES('delete', old.id, old.path);
  INSERT INTO files_fts(rowid, path) VALUES (new.id, new.path);
END;

-- FTS5: symbol names
CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
  name,
  qualified_name,
  content='symbols',
  content_rowid='id',
  tokenize = 'unicode61'
);

CREATE TRIGGER IF NOT EXISTS symbols_ai AFTER INSERT ON symbols BEGIN
  INSERT INTO symbols_fts(rowid, name, qualified_name) VALUES (new.id, new.name, new.qualified_name);
END;
CREATE TRIGGER IF NOT EXISTS symbols_ad AFTER DELETE ON symbols BEGIN
  INSERT INTO symbols_fts(symbols_fts, rowid, name, qualified_name) VALUES('delete', old.id, old.name, old.qualified_name);
END;
CREATE TRIGGER IF NOT EXISTS symbols_au AFTER UPDATE ON symbols BEGIN
  INSERT INTO symbols_fts(symbols_fts, rowid, name, qualified_name) VALUES('delete', old.id, old.name, old.qualified_name);
  INSERT INTO symbols_fts(rowid, name, qualified_name) VALUES (new.id, new.name, new.qualified_name);
END;

-- Optional: full-text over file content when --store-content
CREATE VIRTUAL TABLE IF NOT EXISTS file_contents_fts USING fts5(
  path,
  body,
  tokenize = 'unicode61'
);

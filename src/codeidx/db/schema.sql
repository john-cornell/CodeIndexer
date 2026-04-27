-- Core schema for codeidx v1
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY NOT NULL,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS layer_builds (
  layer TEXT PRIMARY KEY NOT NULL,
  index_version INTEGER NOT NULL DEFAULT 0,
  config_hash TEXT NOT NULL DEFAULT '',
  built_at TEXT NOT NULL DEFAULT ''
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
  kind TEXT NOT NULL
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
  namespace TEXT NOT NULL DEFAULT '',
  return_type TEXT NOT NULL DEFAULT '',
  parameter_types_json TEXT NOT NULL DEFAULT '[]',
  attributes_json TEXT NOT NULL DEFAULT '[]',
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

CREATE TABLE IF NOT EXISTS semantic_components (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  key TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  primary_rule TEXT NOT NULL DEFAULT '',
  source_kind TEXT NOT NULL DEFAULT 'extracted',
  confidence REAL NOT NULL DEFAULT 0.0,
  evidence_symbol_ids TEXT NOT NULL DEFAULT '[]',
  index_version INTEGER NOT NULL DEFAULT 0,
  llm_title TEXT,
  llm_summary TEXT,
  llm_rationale TEXT
);

CREATE TABLE IF NOT EXISTS semantic_component_members (
  component_id INTEGER NOT NULL REFERENCES semantic_components(id) ON DELETE CASCADE,
  symbol_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'member',
  weight REAL NOT NULL DEFAULT 1.0,
  PRIMARY KEY (component_id, symbol_id)
);

CREATE INDEX IF NOT EXISTS idx_component_members_symbol ON semantic_component_members(symbol_id);

CREATE TABLE IF NOT EXISTS semantic_capabilities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  component_id INTEGER NOT NULL REFERENCES semantic_components(id) ON DELETE CASCADE,
  phrase TEXT NOT NULL,
  source_kind TEXT NOT NULL DEFAULT 'extracted',
  confidence REAL NOT NULL DEFAULT 0.0,
  evidence_symbol_ids TEXT NOT NULL DEFAULT '[]',
  index_version INTEGER NOT NULL DEFAULT 0,
  llm_phrasing TEXT,
  llm_nuance TEXT,
  UNIQUE(component_id, phrase)
);

CREATE TABLE IF NOT EXISTS semantic_capability_evidence (
  capability_id INTEGER NOT NULL REFERENCES semantic_capabilities(id) ON DELETE CASCADE,
  method_symbol_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
  PRIMARY KEY (capability_id, method_symbol_id)
);

CREATE TABLE IF NOT EXISTS semantic_flows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_symbol_id INTEGER REFERENCES symbols(id) ON DELETE SET NULL,
  path_signature TEXT NOT NULL,
  source_kind TEXT NOT NULL DEFAULT 'extracted',
  confidence REAL NOT NULL DEFAULT 0.0,
  evidence_symbol_ids TEXT NOT NULL DEFAULT '[]',
  index_version INTEGER NOT NULL DEFAULT 0,
  llm_narration TEXT,
  UNIQUE(entry_symbol_id, path_signature)
);

CREATE TABLE IF NOT EXISTS semantic_flow_steps (
  flow_id INTEGER NOT NULL REFERENCES semantic_flows(id) ON DELETE CASCADE,
  ord INTEGER NOT NULL,
  from_component_id INTEGER REFERENCES semantic_components(id) ON DELETE SET NULL,
  to_component_id INTEGER REFERENCES semantic_components(id) ON DELETE SET NULL,
  edge_id INTEGER REFERENCES edges(id) ON DELETE SET NULL,
  PRIMARY KEY (flow_id, ord)
);

CREATE TABLE IF NOT EXISTS semantic_contract_types (
  type_symbol_id INTEGER PRIMARY KEY REFERENCES symbols(id) ON DELETE CASCADE,
  kind TEXT NOT NULL DEFAULT 'type',
  source_kind TEXT NOT NULL DEFAULT 'extracted',
  confidence REAL NOT NULL DEFAULT 0.0,
  evidence_symbol_ids TEXT NOT NULL DEFAULT '[]',
  index_version INTEGER NOT NULL DEFAULT 0,
  llm_purpose TEXT
);

CREATE TABLE IF NOT EXISTS semantic_component_contracts (
  component_id INTEGER NOT NULL REFERENCES semantic_components(id) ON DELETE CASCADE,
  type_symbol_id INTEGER NOT NULL REFERENCES semantic_contract_types(type_symbol_id) ON DELETE CASCADE,
  direction TEXT NOT NULL DEFAULT 'both',
  edge_id INTEGER REFERENCES edges(id) ON DELETE SET NULL,
  PRIMARY KEY (component_id, type_symbol_id, edge_id)
);

CREATE TABLE IF NOT EXISTS conceptual_terms (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  term TEXT NOT NULL UNIQUE,
  normalized TEXT NOT NULL,
  score REAL NOT NULL DEFAULT 0.0,
  source_kind TEXT NOT NULL DEFAULT 'extracted',
  confidence REAL NOT NULL DEFAULT 0.0,
  evidence_symbol_ids TEXT NOT NULL DEFAULT '[]',
  index_version INTEGER NOT NULL DEFAULT 0,
  gloss TEXT,
  llm_disambiguation TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS conceptual_terms_fts USING fts5(
  term,
  normalized,
  content='conceptual_terms',
  content_rowid='id',
  tokenize = 'unicode61'
);

CREATE TRIGGER IF NOT EXISTS conceptual_terms_ai AFTER INSERT ON conceptual_terms BEGIN
  INSERT INTO conceptual_terms_fts(rowid, term, normalized) VALUES (new.id, new.term, new.normalized);
END;
CREATE TRIGGER IF NOT EXISTS conceptual_terms_ad AFTER DELETE ON conceptual_terms BEGIN
  INSERT INTO conceptual_terms_fts(conceptual_terms_fts, rowid, term, normalized) VALUES('delete', old.id, old.term, old.normalized);
END;
CREATE TRIGGER IF NOT EXISTS conceptual_terms_au AFTER UPDATE ON conceptual_terms BEGIN
  INSERT INTO conceptual_terms_fts(conceptual_terms_fts, rowid, term, normalized) VALUES('delete', old.id, old.term, old.normalized);
  INSERT INTO conceptual_terms_fts(rowid, term, normalized) VALUES (new.id, new.term, new.normalized);
END;

CREATE TABLE IF NOT EXISTS conceptual_term_evidence (
  term_id INTEGER NOT NULL REFERENCES conceptual_terms(id) ON DELETE CASCADE,
  symbol_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
  weight REAL NOT NULL DEFAULT 1.0,
  channel TEXT NOT NULL DEFAULT 'name',
  PRIMARY KEY (term_id, symbol_id, channel)
);

CREATE TABLE IF NOT EXISTS conceptual_synonym_groups (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  representative_term_id INTEGER NOT NULL REFERENCES conceptual_terms(id) ON DELETE CASCADE,
  source_kind TEXT NOT NULL DEFAULT 'extracted',
  confidence REAL NOT NULL DEFAULT 0.0,
  evidence_symbol_ids TEXT NOT NULL DEFAULT '[]',
  index_version INTEGER NOT NULL DEFAULT 0,
  UNIQUE(representative_term_id)
);

CREATE TABLE IF NOT EXISTS conceptual_synonym_group_terms (
  group_id INTEGER NOT NULL REFERENCES conceptual_synonym_groups(id) ON DELETE CASCADE,
  term_id INTEGER NOT NULL REFERENCES conceptual_terms(id) ON DELETE CASCADE,
  link_rule TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (group_id, term_id)
);

CREATE TABLE IF NOT EXISTS conceptual_component_links (
  group_id INTEGER NOT NULL REFERENCES conceptual_synonym_groups(id) ON DELETE CASCADE,
  component_id INTEGER NOT NULL REFERENCES semantic_components(id) ON DELETE CASCADE,
  score REAL NOT NULL DEFAULT 0.0,
  evidence_symbol_ids TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY (group_id, component_id)
);

CREATE TABLE IF NOT EXISTS enrichment_provenance (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  table_name TEXT NOT NULL,
  row_id INTEGER NOT NULL,
  field_name TEXT NOT NULL,
  provider TEXT NOT NULL,
  model_id TEXT NOT NULL,
  prompt_version TEXT NOT NULL DEFAULT '',
  input_hash TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT ''
);

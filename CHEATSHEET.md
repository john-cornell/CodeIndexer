# CodeIndexer Cheat Sheet

Quick commands for indexing, semantic/conceptual builds, querying, and optional enrichment.

## Setup

```powershell
pip install -e ".[dev]"
```

## End-to-end deterministic build

```powershell
python -m codeidx index .
python -m codeidx build-semantic
python -m codeidx build-conceptual
```

## Query basics

```powershell
# Concept lookup
python -m codeidx query concept --term integration

# Component details (members + capabilities)
python -m codeidx query component --component-id 1

# Flows touching a component
python -m codeidx query flow --component-id 1
```

## Optional enrichment (LLM-configurable path)

```powershell
# Deterministic no-op enrichment
python -m codeidx enrich --provider none --model none

# Ollama-style selection
python -m codeidx enrich --provider ollama --model llama3

# Cloud-style selection
python -m codeidx enrich --provider cloud --model gpt-4o-mini
```

Notes:
- `index`, `build-semantic`, and `build-conceptual` are deterministic and do not use LLM.
- `enrich` is the only command that writes LLM-related nullable fields and enrichment provenance.

## Query enrichment output

```powershell
# Latest enrichment rows
python -m codeidx query enrichment --limit 20

# Filter by table
python -m codeidx query enrichment --table semantic_components --limit 20

# Filter by provider
python -m codeidx query enrichment --provider ollama --limit 20
```

## One-shot run

```powershell
python -m codeidx index .; `
python -m codeidx build-semantic; `
python -m codeidx build-conceptual; `
python -m codeidx enrich --provider ollama --model llama3
```

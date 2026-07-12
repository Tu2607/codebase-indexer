# Architecture

## Design goals

The v0 architecture favors a small, understandable local system over broad
language support or sophisticated code intelligence. It uses Python, FastMCP,
ChromaDB's `PersistentClient`, ChromaDB's default local embeddings, and a
repository-local `.codebase-index` directory.

The index accelerates discovery; files on disk remain authoritative.

## System shape

```text
MCP client
    |
    v
server.py (tool definitions and error translation)
    |
    +--> indexer.py / reindexer.py (workflows)
    |        |
    |        +--> file_finder.py
    |        +--> hashing.py
    |        +--> chunker.py
    |        +--> index_store.py --> ChromaDB
    |
    +--> results.py (structured return contracts)
```

Expected package layout:

```text
src/codebase_indexer/
  __init__.py
  server.py
  config.py
  file_finder.py
  chunker.py
  hashing.py
  index_store.py
  indexer.py
  reindexer.py
  results.py
  path_utils.py
  repo_id.py
```

## Module boundaries

- `config.py` owns file allowlists, skipped directories, size and chunk
  defaults, worker and batch defaults, the persistence directory, and the
  collection name.
- `hashing.py` computes SHA-256 hashes from raw file bytes.
- `file_finder.py` decides whether a file is indexable and walks a repository,
  returning canonical eligible files and a discovery skip count.
- `chunker.py` performs overlapping line-based chunking.
- `index_store.py` contains ChromaDB client and collection access, chunk writes
  and deletion, queries, and index metadata/status operations.
- `indexer.py` orchestrates initialization with bounded preparation workers,
  serialized ChromaDB writes, batching, and partial-failure reporting.
- `reindexer.py` implements the single-file update workflow.
- `results.py` defines structured dictionary contracts and constructors.
- `path_utils.py` validates and normalizes repository and file paths.
- `repo_id.py` provides stable repository identity used by stored records.
- `server.py` owns FastMCP tool definitions and translates domain failures into
  MCP-facing errors.

MCP definitions stay in `server.py`; logic that can be tested independently
belongs in helper modules.

## File selection

The allowlist reflects the owner's normal stack instead of attempting to index
every language.

Indexed extensions:

```text
.go .py .js .jsx .ts .tsx .json .toml .yaml .yml .md .sh .sql
```

Indexed exact filenames:

```text
Dockerfile             Makefile           Taskfile.yml
docker-compose.yml     compose.yml        go.mod
go.sum                 package.json       package-lock.json
pnpm-lock.yaml         yarn.lock          pyproject.toml
requirements.txt       README.md
```

Skipped directories:

```text
.git            .codebase-index  .venv          venv
__pycache__     node_modules      vendor         dist
build           .next             .pytest_cache  .mypy_cache
coverage
```

Files larger than 300 KiB are skipped in v0.

## Chunk and record model

Files are split into chunks of 80 lines with a 10-line overlap by default.
Each stored chunk includes:

- `repo_path`
- `file_path`
- `relative_path`
- `start_line`
- `end_line`
- `file_hash`

A chunk identifier may combine repository identity, relative path, chunk
position, and a hash prefix:

```text
{repo_hash}:{relative_path}:{chunk_index}:{file_hash_prefix}
```

This model is deliberately text-oriented. V0 does not perform AST-aware or
language-specific splitting.

## Hashing and staleness

SHA-256 is computed over the original file bytes, not normalized text. The hash
supports stale-result detection, chunk identity, and reporting whether stored
content matches the current file.

Staleness checks happen during retrieval, but updates remain explicit. Search
must not trigger background or automatic reindexing.

## Initialization and updates

`index_repo` is initialization-only. For a new index, file preparation can use
bounded workers, while ChromaDB writes remain serialized and batched. A failure
for one eligible file should not discard successful work; the result reports
partial failures for targeted recovery.

For a healthy existing index, initialization is a no-op. Routine changes use
`reindex_file`, which replaces one file's records, or
`delete_file_from_index`, which removes them.

A corrupted index is reported rather than repaired implicitly. A future
explicit rebuild workflow will own destructive recovery.

## Deliberate non-goals for v0

- OpenAI API or other external embedding services.
- AST parsing or Tree-sitter.
- LLM-generated summaries.
- File watchers, schedulers, or background daemons.
- Background reindexing during search.
- Symbol graphs, call graphs, or deeper semantic indexing.
- Generalized support for every programming language.

These constraints keep the implementation local, predictable, and suitable as
a learning project.

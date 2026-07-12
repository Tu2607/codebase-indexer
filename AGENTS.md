# AGENTS.md

Guidance for Codex and other coding agents working in this repository.

## Project Summary

This repository is a small Python MCP server called `codebase-indexer-mcp`.

The goal is to build a lightweight, personal-use repository context retrieval
tool for Codex and Claude using FastMCP and ChromaDB. It is intentionally a
learning project and should stay simple in v0. It is not intended to become a
production-grade CocoIndex replacement.

The server should:

- Index important files from a local repository into ChromaDB.
- Chunk files into simple line-based chunks.
- Use ChromaDB's default local embedding function for vector search.
- Expose MCP tools that let an LLM agent discover relevant repo context.
- Support re-indexing individual files after edits.
- Detect stale indexed content using file hashes.

Core principle:

The indexer is a context discovery tool, not the source of truth for editing.

## Agent Workflow

When using this MCP server as an agent:

1. Use `search_repo_context` to discover likely relevant files and code regions.
2. Read target files directly from disk before editing them.
3. Edit files normally.
4. After editing each indexed file, call `reindex_file` for that file.
5. After deleting an indexed file, call `delete_file_from_index`.
6. Do not call `index_repo` repeatedly during normal work.

Use `index_repo` during first setup or when no usable index exists. It is
initialization-only and does not refresh a healthy existing index. Do not rely
on it to update an index after pulling large changes; use explicit file updates
or the repository's future rebuild workflow instead.

Search results are hints. They are not complete context, and they may be stale.

## Technology Choices

Use:

- Python.
- FastMCP.
- ChromaDB `PersistentClient`.
- ChromaDB default embeddings.
- A local persistent index directory, likely `.codebase-index`.

Do not add in v0:

- OpenAI API embeddings.
- AST parsing.
- Tree-sitter.
- LLM-generated summaries.
- File watchers.
- Symbol graphs, call graphs, or deep semantic indexing.
- Background auto-reindexing during search.

## Expected Layout

Prefer this layout unless there is a strong reason to change it:

```text
codebase-indexer-mcp/
  pyproject.toml
  README.md
  AGENTS.md
  src/
    codebase_indexer/
      __init__.py
      server.py
      config.py
      file_finder.py
      chunker.py
      hashing.py
      index_store.py
      indexer.py
      results.py
  tests/
```

Module responsibilities:

- `config.py`: extension allowlist, filename allowlist, skipped directories,
  max file size, chunk defaults, index worker and batch defaults, Chroma
  persist path, collection name.
- `hashing.py`: SHA-256 file hashing helper.
- `file_finder.py`: file filtering and repository walking, including
  `should_index_file(path)` and `iter_indexable_files(repo_path)`, which
  returns eligible canonical files and a discovery skip count.
- `chunker.py`: line-based chunking, including `chunk_by_lines(path,
  chunk_size, overlap)`.
- `index_store.py`: ChromaDB client setup, collection access, adding chunks,
  deleting chunks for a file, querying chunks, and metadata/status helpers.
- `indexer.py`: initialization-only repository orchestration, including
  bounded worker preparation, serialized Chroma writes, and partial-failure
  reporting.
- `results.py`: TypedDict contracts and constructors for initialization,
  partial failures, and single-file reindex results.
- `server.py`: FastMCP app, MCP tool definitions, and glue logic between the
  other modules.

Keep MCP tool definitions in `server.py`. Keep logic that is easy to unit test
in the helper modules.

## File Selection

This project is personal-use and should be tailored to the owner's normal
stack instead of trying to support every language.

Index these extensions:

- `.go`
- `.py`
- `.js`
- `.jsx`
- `.ts`
- `.tsx`
- `.json`
- `.toml`
- `.yaml`
- `.yml`
- `.md`
- `.sh`
- `.sql`

Index these exact filenames:

- `Dockerfile`
- `Makefile`
- `Taskfile.yml`
- `docker-compose.yml`
- `compose.yml`
- `go.mod`
- `go.sum`
- `package.json`
- `package-lock.json`
- `pnpm-lock.yaml`
- `yarn.lock`
- `pyproject.toml`
- `requirements.txt`
- `README.md`

Skip these directories:

- `.git`
- `.venv`
- `venv`
- `__pycache__`
- `node_modules`
- `vendor`
- `dist`
- `build`
- `.next`
- `.pytest_cache`
- `.mypy_cache`
- `coverage`

Also skip files larger than about 300 KB in v0.

## Chunking

Use simple line-based chunking.

Initial defaults:

- Chunk size: 80 lines.
- Overlap: 10 lines.

Each chunk should include metadata:

- `repo_path`
- `file_path`
- `relative_path`
- `start_line`
- `end_line`
- `file_hash`

Chunk IDs may be based on:

- Repository identifier or hash.
- Relative path.
- Chunk index.
- File hash prefix.

Example:

```text
{repo_hash}:{relative_path}:{chunk_index}:{file_hash_prefix}
```

Avoid clever chunking in v0. Do not add AST-aware splitting or language-specific
parsing unless the user explicitly changes the scope.

## Hashing

Use SHA-256 file hashes.

Hashes are used for:

- Detecting stale search results.
- Creating stable-ish chunk IDs.
- Reporting whether indexed content is current.

Hash file bytes, not normalized text, unless there is a concrete reason to
change that behavior.

## MCP Tools

### `index_repo(repo_path: str) -> dict`

Initializes an index for a repository that does not have a usable index.
Calling it for a healthy existing index returns immediately without walking or
mutating the repository index.

Expected behavior:

- Validate that `repo_path` is an existing directory.
- If no usable index exists, create the repository-local index and continue
  with the initial walk.
- If a healthy index already exists, return an initialized result with
  `created=false` and do not walk or mutate the index.
- Walk the repo recursively.
- Skip ignored directories.
- Index only files matching the tailored file rules.
- Prepare files with SHA-256 hashing and line-based chunking.
- Continue when an eligible file fails during preparation or writing, and
  report the failed files in a partial-failure error for later
  `reindex_file` recovery.
- Return counts for indexed files, skipped files, and indexed chunks.

If the existing index is corrupted or unavailable, raise an error with
recovery guidance. `index_repo` does not attempt to repair or rebuild a
corrupted index.

Do not use this as the normal post-edit update path. Use `reindex_file` after
individual edits.

### `reindex_file(repo_path: str, file_path: str) -> dict`

Re-indexes one file after it has been edited, created, or overwritten. The
repository path must be passed explicitly; the server does not discover it.

Expected behavior:

- If the file does not exist, delete any existing chunks for it from the index.
- If the file exists but is not indexable, return a skipped response.
- If the file exists and is indexable:
  - Compute its file hash.
  - Delete old chunks for that file.
  - Chunk the current file.
  - Add new chunks to ChromaDB.
  - Return chunk count and hash.

This is the main tool an agent should call after editing indexed files.

### `delete_file_from_index(repo_path: str, file_path: str) -> dict`

Removes a file's chunks from the index.

Use this after deleting or renaming a file.

For renamed files, the expected workflow is:

1. `delete_file_from_index(repo_path, old_path)`
2. `reindex_file(repo_path, new_path)`

### `search_repo_context(repo_path: str, query: str, max_results: int = 5, include_stale: bool = False) -> list[dict]`

Searches indexed repository chunks.

All index-backed tools require `repo_path` to be passed explicitly. The server
does not discover or infer the repository path.

Expected behavior:

- Query ChromaDB using the given query text.
- Return top matching chunks.
- Include file path.
- Include relative path when available.
- Include start and end line.
- Include distance or score.
- Include chunk content.
- Compare the current file hash against the indexed hash.
- Mark results as stale if files have changed since indexing.

If `include_stale` is false, either filter stale results or make stale warnings
very clear. Prefer predictable behavior over hidden auto-updates.

Tool description should clearly tell agents:

Use this tool to discover relevant files and code regions. Do not treat search
results as complete context for editing. Before modifying a file, read the
target file directly from disk. After modifying any indexed file, call
`reindex_file` for that file.

### `get_index_status(repo_path: str | None = None) -> dict`

Returns index debugging information.

Useful output:

- Number of indexed files.
- Number of indexed chunks.
- Sample indexed paths.
- Possibly stale files.
- Index path.
- Collection name.

### Future: `rebuild_index(repo_path: str) -> dict`

This tool is not implemented yet. It is reserved for explicit recovery when
the existing Chroma database or collection cannot be opened. Rebuilding may
replace local index data, so neither `index_repo` nor `reindex_file` should
invoke it automatically.

## Stale Index Policy

Indexed content can become stale when Codex, Claude, or a user edits files.
Do not re-index the entire repository after every prompt.

Policy for v0:

- Agents should call `reindex_file` after editing any indexed file.
- `search_repo_context` should detect stale results by comparing the current
  file hash to the indexed hash.
- Stale results must be clearly marked.
- `search_repo_context` should not automatically re-index stale files.
- Keep search predictable and make indexing updates explicit.

## Implementation Rules

- Keep v0 boring and readable.
- Prefer small, testable functions over broad abstractions.
- Do not introduce external services for embeddings.
- Do not add a watcher, scheduler, or background daemon.
- Do not overgeneralize language support.
- Keep configuration centralized in `config.py`.
- Keep Chroma-specific behavior behind `index_store.py`.
- Use structured metadata for paths, lines, hashes, and repo identity.
- Handle missing files gracefully.
- Return plain dictionaries/lists from MCP tools with enough detail for agents
  to understand what happened.
- Make MCP tool descriptions explicit because they guide agent behavior.

## Testing Guidance

Add focused tests where behavior is easy to get wrong:

- File filtering and skipped directories.
- Maximum file size behavior.
- Line-based chunk boundaries and overlap.
- SHA-256 hash changes.
- Re-indexing a changed file.
- Deleting chunks for missing or deleted files.
- Stale result detection.

Tests should be practical and local. Avoid tests that require network access.

## Definition of Done for v0

v0 is done when:

1. The FastMCP server starts.
2. `index_repo` can index a local repository.
3. `search_repo_context` returns relevant chunks with file paths and line
   numbers.
4. `reindex_file` updates the index for one edited file.
5. `search_repo_context` can mark stale results when a file has changed since
   indexing.
6. `README.md` explains how to run the server and how agents should use the
   tools.

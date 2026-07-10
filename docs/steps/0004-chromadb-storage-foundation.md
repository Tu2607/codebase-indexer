# 0004 ChromaDB Storage Foundation

Date: 2026-07-09
Status: implemented

## Goal

Establish repository-local ChromaDB persistence so future indexing work can
reuse stored chunks and embeddings without walking source files on every server
start or search.

## Changes

- Added `chromadb` to `Pipfile` and regenerated `Pipfile.lock`.
- Added `.tool-versions` to select standard CPython 3.14.3 for this project.
- Added `.gitignore` coverage for this repository's generated index directory.
- Added `src/codebase_indexer/index_store.py` with `IndexStore`.
- Added focused ChromaDB lifecycle tests in `tests/test_index_store.py`.

## Decisions

- Store each repository's ChromaDB data under
  `{resolved_repo_path}/.codebase-index`.
- Reserve `.codebase-index` in `SKIP_DIRECTORIES` so later file discovery does
  not index ChromaDB's own database files. This repository ignores that local
  directory; the server does not modify `.gitignore` files in target repos.
- `IndexStore` resolves and validates the repository path before opening
  ChromaDB. Missing paths and file paths raise `ValueError`; ChromaDB errors
  otherwise propagate unchanged.
- The store creates a `PersistentClient` and gets or creates the configured
  collection using ChromaDB's default collection settings and embedding
  function.
- Opening `IndexStore` again for the same repository reuses ChromaDB's existing
  database files, including documents, metadata, and embeddings. It does not
  walk repository files or re-embed content.
- Use standard, GIL-enabled CPython 3.14.3. The available free-threaded
  CPython 3.14 build cannot install ChromaDB's `onnxruntime` dependency on
  macOS ARM64.
- Keep the production store API limited to lifecycle access, resolved paths,
  collection access, and collection count. Chunk CRUD and search remain later
  steps.
- The persistence test writes a fixture record with an explicit embedding
  directly through Chroma's collection API. This verifies local persistence
  without invoking or downloading the default embedding model; it is not an
  application raw-vector API.

## Tests

- Creates a repository-local index directory and configured collection.
- Reports an empty collection on first creation.
- Reopens a persisted test record, document, and metadata from the same index
  directory.
- Normalizes repository paths and derives the index directory beneath them.
- Resolves a symlinked repository path to the directory that owns the index.
- Reserves the generated index directory for future file-discovery skips.
- Rejects missing paths and file paths as repository roots.
- `pipenv run pytest` passes: 49 tests.

## Follow-ups

- Add chunk storage CRUD that sends chunk IDs, documents, and metadata to
  ChromaDB; ChromaDB will create and persist embeddings internally.
- Add file discovery and reindex orchestration using the existing hash and
  chunk helpers.
- Add search results and stale-index detection.

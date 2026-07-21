# Repository guidance

## Required Index-First Workflow

For every repository task that requires codebase context:

1. Call `index_repo`.
2. Call `get_index_status`.
3. Reconcile the index:
   - Use `reindex_file` for new or changed files.
   - Use `delete_file_from_index` for deleted files and old rename paths.
4. Verify the index is clean with `get_index_status`.
5. Call `search_repo_context` with a concise feature, behavior, or symbol query.
6. Read the returned source regions directly.
7. Use targeted `rg`, grep, or glob searches to find definitions, callers, references, and tests.

Treat index results as navigation pointers. The current working tree remains the source of truth. Avoid broad scans and whole-file reads unless the indexed pointers are insufficient.

After all edits, formatting, generation, or other file-changing commands:

1. Call `get_index_status`.
2. Reindex changed files and remove deleted paths from the index.
3. Call `get_index_status` again.
4. Do not report completion until the index is clean. Report any unresolved indexing errors.

If an approved background watcher is active, it may perform routine synchronization, but the agent must still verify clean status before searching and before completion.

Required flow:

index → verify/synchronize → search context → read pointers → targeted text search → make changes → verify/synchronize → complete

If the indexer is unavailable or unusable, state that briefly and fall back to targeted rg, grep, glob, and direct source reads.

## Working rules

- Focus on the happy path. The simplest implementation that satisfies the
  agreed scope wins; do not add speculative behavior or reach beyond that
  scope.
- Ask the developer or user for permission before editing any file. Do not
  infer edit authorization from context or make unapproved assumptions.
- If a plan or requested implementation conflicts with a documented
  architectural decision, stop before editing, identify the conflict, and ask
  the developer or user which direction to follow.
- Keep v0 small, readable, and local-first.
- Keep MCP tool definitions in `server.py` and testable logic in helper modules.
- Keep configuration centralized in `config.py` and ChromaDB behavior isolated
  in `index_store.py`.
- Add focused, local tests for changed behavior and avoid network-dependent
  tests.
- Do not expand the v0 scope with external embeddings, AST parsing, watchers,
  background reindexing, or semantic code graphs unless explicitly requested.

## Project overview

`codebase-indexer-mcp` is a single-package Python MCP server. It is not a
monorepo and has no separate apps or services.

- **Runtime:** standard, GIL-enabled CPython 3.14.3, selected by
  `.tool-versions`. Do not use the free-threaded Python build; ChromaDB's
  `onnxruntime` dependency is not available for it on macOS ARM64.
- **Dependency tooling:** Pipenv with `Pipfile` and `Pipfile.lock`. Use
  `pipenv`, not direct `pip` commands.
- **Server framework:** FastMCP.
- **Storage and search:** ChromaDB `PersistentClient` with its default local
  embedding function and a repository-local `.codebase-index` directory.
- **Tests:** pytest, configured by `pytest.ini` to import the `src/` package.

Repository structure:

```text
src/codebase_indexer/   MCP tools and indexer implementation
tests/                  focused unit and local integration tests
docs/FUNCTIONAL_SPEC.md tool contracts, lifecycle rules, and edge cases
docs/ARCHITECTURE.md    design decisions and module responsibilities
docs/steps/             chronological implementation records and plans
Pipfile                 runtime and development dependencies
pytest.ini              test discovery and src-layout import configuration
```

Within `src/codebase_indexer/`, `server.py` defines the MCP surface;
`indexer.py` and `reindexer.py` orchestrate workflows; `index_store.py` owns
ChromaDB access; `file_finder.py`, `chunker.py`, and `hashing.py` prepare source
content; and the remaining modules handle configuration, paths, repository
identity, and result contracts.

For detailed contracts, read:

- [`docs/FUNCTIONAL_SPEC.md`](docs/FUNCTIONAL_SPEC.md) for implementation
  status, detailed tool contracts, lifecycle rules, and filesystem edge cases.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for design decisions, module
  boundaries, indexing rules, and technical constraints.
- [`docs/steps/README.md`](docs/steps/README.md) for the incremental
  implementation plan and current work sequence.

## Purpose and principles

The project gives Codex and Claude a lightweight, personal-use way to discover
relevant regions in local repositories without an external embedding service.
It is intentionally a learning-oriented v0, not a production-grade CocoIndex
replacement.

The index accelerates context discovery, but files on disk remain the source of
truth. Explicit per-file updates keep indexing predictable and avoid the
complexity of watchers or automatic background work.

## Development and verification

From the repository root:

```bash
pipenv install --dev
pipenv run pytest
```

Use narrower pytest runs while iterating, then run the full suite before
finishing:

```bash
pipenv run pytest tests/test_chunker.py
pipenv run pytest tests/test_server.py -k reindex
pipenv run pytest
```

End-to-end lifecycle smoke tests live in `tests/test_smoke.py` under the
`smoke` marker and are excluded from the default run because they load the
real embedder. Run them on demand and before tagging a release:

```bash
pipenv run pytest -m smoke
```

There is currently no packaged build step or runnable CLI entry point. Verify
server construction with an import when relevant:

```bash
PYTHONPATH=src pipenv run python -c "from codebase_indexer.server import mcp; print(mcp.name)"
```

For documentation-only changes, run `git diff --check`; Python tests are not
required unless the documentation change describes executable behavior that
should be validated.

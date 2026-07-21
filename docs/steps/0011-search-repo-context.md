# Step 0011: Implement `search_repo_context`

## Outcome

Implemented the final v0 MCP tool as a read-only semantic locator. ChromaDB
embeds one validated query, retrieves the nearest indexed chunks, and the tool
returns ordered repository-relative file and line-range pointers for direct
filesystem inspection.

The default result limit is 10. Search returns fewer pointers when ChromaDB has
fewer candidates or stale candidates are filtered out.

## Changes

- Added `DEFAULT_SEARCH_MAX_RESULTS` to centralized configuration.
- Added the `SearchMatch` plain-dictionary contract and constructor.
- Added `IndexStore.query_chunks` to isolate the ChromaDB query and unwrap its
  single-query metadata response.
- Added `searcher.py` for metadata validation, repository-safe path resolution,
  staleness checks, per-call file-hash memoization, filtering, and result
  construction.
- Replaced the FastMCP scaffold with the implemented handler and expected error
  translation.
- Updated the functional specification and architecture documentation.
- Added focused store, searcher, result-contract, and MCP-handler tests.

## Decisions

- Results contain only `relative_path`, one-based `start_line`, `end_line`, and
  `stale`. V0 does not return documents, absolute paths, distances, embeddings,
  or indexed hashes.
- ChromaDB receives exactly `max_results`; search does not over-fetch after
  stale filtering.
- Current file hashes are memoized by relative path only within one tool call.
  No persistent cache or invalidation lifecycle was added.
- Every candidate is validated before filesystem hashing begins. Malformed
  metadata fails the complete search rather than being silently skipped.
- Stored paths must be normalized and remain inside the repository after
  symlink resolution.
- A focused `SearchMetadataError` distinguishes expected metadata failures from
  unrelated ChromaDB or infrastructure failures. Only the former is translated
  to FastMCP `ToolError` by the server.
- Search never calls status, reindex, deletion, or other mutation workflows.

## Staleness behavior

A match is stale when its file is missing, cannot be hashed, changes during
hashing, or no longer matches its stored byte-level SHA-256 hash. Stale matches
are omitted by default and included with `stale: true` only when requested.

## Validation

Focused search, store, and server suite:

```text
160 passed
```

Full suite:

```text
315 passed
```

The suite remains network-independent. The only warning is ChromaDB's existing
use of an asyncio API deprecated for removal in Python 3.16.

## Follow-up

V0 intentionally leaves distance thresholds, over-fetching, deduplication,
reranking, batch queries, persistent caches, and richer returned context for
future changes driven by observed usage.

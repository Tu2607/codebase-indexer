# Plan: Implement `get_index_status`

## Goal

Implement a read-only repository/index comparison that tells an MCP caller
which individual paths need `reindex_file` and which need
`delete_file_from_index`. It must never repair, reindex, or delete content.

The intended lifecycle is:

```text
get_index_status
  -> reindex each new or changed eligible path
  -> delete each missing or no-longer-indexable indexed path
  -> optionally call get_index_status again to verify
```

## Public contract

Make repository selection explicit and consistent with every other index-backed
tool:

```text
get_index_status(repo_path: str) -> dict
```

Recommended result shape:

```json
{
  "status": "changes_detected",
  "repo_path": "/absolute/repo",
  "index_path": "/absolute/repo/.codebase-index",
  "collection_name": "codebase",
  "indexed_files": 12,
  "indexed_chunks": 37,
  "files_to_reindex": [
    {"relative_path": "src/new.py", "reason": "not_indexed"},
    {"relative_path": "src/changed.py", "reason": "content_changed"}
  ],
  "files_to_delete": [
    {"relative_path": "src/old.py", "reason": "missing"},
    {"relative_path": "src/image.png", "reason": "no_longer_indexable"}
  ],
  "files_with_errors": []
}
```

Use `status: "clean"` when both action lists and the error list are empty.
Sort every path list by `relative_path` for deterministic LLM output and tests.

Each error entry should contain `relative_path` and `reason`. Errors are
diagnostic only: do not classify a path for deletion when the current state
cannot be read safely.

## Comparison rules

Build a file-level view of the index from chunk metadata, grouping records by
`relative_path` and reading their stored `file_hash`.

For each indexed path:

- Missing on disk -> `files_to_delete`, reason `missing`.
- Existing but rejected by `should_index_file` -> `files_to_delete`, reason
  `no_longer_indexable`.
- Existing and eligible with a current hash different from the indexed hash ->
  `files_to_reindex`, reason `content_changed`.
- Existing and eligible with the same hash -> no action.
- Filesystem or hashing failure -> `files_with_errors`; preserve indexed data.

For each currently eligible path discovered by `iter_indexable_files` but not
present in the indexed file view:

- Add to `files_to_reindex`, reason `not_indexed`.

Do not attempt to infer that one missing path and one new path form a rename.
They remain an explicit delete action and an explicit reindex action.

If chunk metadata for one path contains conflicting file hashes, report the
path as `files_to_reindex` with reason `inconsistent_index` rather than choosing
one hash silently.

## Proposed design

### `src/codebase_indexer/index_store.py`

Add one read-only method that returns the metadata required to build the
file-level view, for example:

```text
get_indexed_file_metadata() -> list[dict[str, object]]
```

It should call the Chroma collection with `include=["metadatas"]` and expose no
documents or embeddings. ChromaDB query details remain isolated in this
module. The status layer performs grouping and validation.

The existing `collection_count()` supplies `indexed_chunks`.

### `src/codebase_indexer/status.py`

Add a testable orchestration helper such as:

```text
get_repository_index_status(store, repo_path) -> IndexStatusResult
```

It should:

1. Read and group indexed metadata by normalized relative path.
2. Discover the current eligible filesystem paths with
   `iter_indexable_files`.
3. Compare indexed paths to disk state using `should_index_file` and
   byte-level `hash_file`.
4. Produce deterministic action/error lists and aggregate counts.
5. Perform no store writes and invoke no MCP tools.

Avoid hashing the same eligible file twice: cache the discovery result and its
hash within the status operation. V0 may scan and hash the repository on every
explicit status call; do not add caches, watchers, or background work.

### `src/codebase_indexer/results.py`

Add typed dictionaries and constructors for:

- Reindex action: `relative_path`, `reason`.
- Delete action: `relative_path`, `reason`.
- Status error: `relative_path`, `reason`.
- Top-level index status result.

Keep the JSON shape plain and stable. Do not include absolute per-file paths
unless a consumer need is established; the resolved repository path plus a
relative path is sufficient.

### `src/codebase_indexer/server.py`

- Change `repo_path` from optional to required.
- Validate it and open the existing healthy index.
- Translate expected repository, uninitialized-index, and corrupted-index
  failures to `ToolError`.
- Delegate to the read-only status helper.
- Update the description to say it compares disk and index state and reports
  explicit follow-up actions without applying them.

## Empty-file limitation

The current index stores only chunks. A successfully indexed empty eligible
file produces zero chunks, so there is no persistent record proving it was
indexed. A chunk-derived status implementation will consequently report such a
file as `not_indexed` on every call.

For v0, accept and document this conservative false positive: reindexing the
empty file is safe and idempotent. Do not introduce a second manifest,
sentinel-vector records, or storage migration solely for this edge case in this
step. File-level state can be added later if empty-file stability becomes
important. A future manifest must be maintained atomically enough by
`index_repo`, `reindex_file`, and `delete_file_from_index` to avoid creating a
second source of drift.

## Failure and race behavior

- Status is a point-in-time best effort; files can change after it returns.
- A file changing during hashing goes to `files_with_errors` with a retryable
  explanation and is not scheduled for deletion.
- A file disappearing during inspection is classified as missing only when it
  was already indexed; a newly discovered file that disappears is reported as
  an error or omitted consistently, never deleted.
- Permission and read failures go to `files_with_errors` and preserve indexed
  data.
- Invalid or incomplete chunk metadata becomes an error, not a destructive
  recommendation.
- ChromaDB read failures surface as tool failures; do not return a misleading
  partial `clean` result.

## Tests

### `tests/test_status.py`

- Clean repository returns `clean` and empty action/error lists.
- Changed hash produces `content_changed` reindex action.
- Eligible path absent from indexed metadata produces `not_indexed`.
- Missing indexed path produces a `missing` delete action.
- Existing indexed path that becomes unsupported, oversized, or otherwise
  ineligible produces `no_longer_indexable`.
- Rename-shaped state produces independent old-path deletion and new-path
  reindex actions.
- Conflicting indexed hashes produce `inconsistent_index`.
- Hashing, permission, disappearance, and malformed-metadata cases never
  recommend unsafe deletion.
- Lists are stable and sorted.
- Store write methods are never called.
- Empty files exhibit the documented conservative `not_indexed` behavior.

### `tests/test_index_store.py`

- Metadata reads request metadatas without documents or embeddings.
- Multiple chunks for one file are returned for status-layer grouping.
- Empty collections return an empty list.

### `tests/test_results.py` and `tests/test_server.py`

- Verify exact result/action shapes.
- Require explicit `repo_path` in the public signature.
- Cover validation and healthy-index wiring.
- Convert expected index lifecycle errors to `ToolError`.
- Confirm FastMCP dispatch returns status data and performs no mutation.

Run:

```bash
pipenv run pytest tests/test_status.py tests/test_index_store.py tests/test_results.py tests/test_server.py -k status
pipenv run pytest
```

## Documentation

- Mark status implemented in `docs/FUNCTIONAL_SPEC.md` and replace its current
  debugging-only description with the actionable read-only contract.
- Update `docs/ARCHITECTURE.md` with the inspect-then-mutate lifecycle.
- Document the rename workflow as independent delete and reindex actions.
- Document the empty-file limitation until file-level index state exists.

## Non-goals

- Applying reported actions automatically.
- Batch mutation, rename pairing, filesystem watchers, caching, or background
  synchronization.
- Repairing corrupted or inconsistent indexes.
- Adding a file manifest or migrating existing indexes in v0.

## Dependencies

Implement after Steps 7 and 8 so every suggested action maps to a tool with the
agreed non-overlapping behavior.

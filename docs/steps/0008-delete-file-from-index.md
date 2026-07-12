# Plan: Implement `delete_file_from_index`

## Goal

Implement an explicit, single-path MCP operation that deletes every indexed
chunk associated with a repository-relative path. It is the only tool that
performs file-level index removal.

Primary uses are a deleted file, the old path of a rename, and an existing file
that no longer qualifies for indexing.

## Contract

```text
delete_file_from_index(repo_path: str, file_path: str) -> dict
```

`file_path` may be relative to the repository or absolute within it. The
filesystem target may exist or be missing. The operation normalizes it to a
POSIX repository-relative path and deletes all matching chunks.

Successful result:

```json
{
  "status": "deleted",
  "relative_path": "src/old_name.py",
  "chunks_removed": 3
}
```

The operation is idempotent. A valid path with no matching chunks returns the
same status with `chunks_removed: 0`.

Reject an empty path, the repository root, a path that resolves outside the
repository, an invalid repository, an uninitialized index, or a corrupted
index. Whether the target is currently indexable is irrelevant: this tool
addresses indexed identity by normalized path and does not read or hash file
content.

## Proposed design

### Deletion orchestrator

Add a small helper module such as `src/codebase_indexer/deleter.py` with a
testable function:

```text
delete_indexed_file(store, file_path, repo_path) -> DeletedResult
```

It should:

1. Use `resolve_repo_file_path` so existing and missing paths share the same
   containment and normalization rules as other single-file tools.
2. Call `store.delete_chunks_for_file(relative_path)` exactly once.
3. Return `deleted_result(relative_path, chunks_removed)`.

Keep ChromaDB access in `IndexStore`; the helper only coordinates path
normalization and result construction.

### MCP boundary

Replace the scaffold in `server.py` with the same boundary pattern used by
`reindex_file`:

- Validate and trim `repo_path`.
- Require and trim `file_path` before opening the store.
- Open the existing healthy index with `IndexStore.open_existing`.
- Translate expected validation, uninitialized-index, and corrupted-index
  failures into `ToolError`.
- Delegate to the deletion orchestrator.
- Do not call `reindex_file` or inspect the filesystem for eligibility.

Update the MCP description to emphasize explicit removal and the rename
workflow:

```text
delete_file_from_index(old_path)
reindex_file(new_path)
```

### Store and result layers

Reuse the existing `IndexStore.delete_chunks_for_file` and
`deleted_result`. No new ChromaDB deletion primitive or result shape is needed.
If the status plan later introduces file-level state, this operation must delete
that state in the same orchestrated operation; do not leave a path recorded as
indexed after its chunks are removed.

## Failure behavior

| Condition | Behavior |
| --- | --- |
| Existing indexed path | Delete all chunks and return their count |
| Missing indexed path | Delete all chunks and return their count |
| Valid unindexed path | Return `deleted` with zero removed |
| Existing unindexable path | Delete matching indexed chunks |
| Path outside repository | `ToolError`, no store mutation |
| Index not initialized/corrupted | `ToolError`, no mutation |
| ChromaDB deletion failure | Surface the failure; do not report success |

The count is obtained before deletion because ChromaDB deletion does not return
a count. A failure after that read must not produce a successful result.

## Tests

### `tests/test_deleter.py`

- Existing indexed path delegates using its normalized relative path.
- Missing path is accepted and deletes by normalized relative path.
- Absolute in-repository paths are accepted.
- Paths outside the repository and the repository root fail before mutation.
- Known and unknown paths return accurate counts.
- The orchestrator performs no hashing, eligibility check, or reindexing.

### `tests/test_server.py`

- Wire the tool to `open_existing` and the deletion orchestrator.
- Trim repository and file-path whitespace.
- Reject missing/blank inputs before opening the index.
- Convert expected path and index lifecycle errors to `ToolError`.
- Do not swallow unexpected orchestrator failures.
- Replace the scaffolded-tool assertion with FastMCP dispatch coverage.

### Existing store/results coverage

Retain focused tests that `delete_chunks_for_file` removes every matching chunk,
does not affect other paths, and returns zero for an unknown path. Retain the
exact `deleted_result` shape test.

Run:

```bash
pipenv run pytest tests/test_deleter.py tests/test_index_store.py tests/test_results.py tests/test_server.py -k delete
pipenv run pytest
```

## Documentation

- Mark the tool implemented in `docs/FUNCTIONAL_SPEC.md` and document its
  idempotent semantics.
- Update lifecycle and rename examples in `docs/FUNCTIONAL_SPEC.md` and
  `docs/ARCHITECTURE.md`.
- Ensure `reindex_file` documentation no longer recommends implicit deletion.

## Non-goals

- Discovering which paths should be deleted.
- Pairing old and new paths into a semantic rename.
- Deleting filesystem files.
- Batch deletion, wildcard paths, automatic cleanup, or index rebuilding.

## Dependency

Implement after or alongside Step 7 so the public tool descriptions and result
unions consistently enforce explicit file-level deletion.

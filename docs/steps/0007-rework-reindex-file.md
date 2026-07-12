# Plan: Rework `reindex_file`

## Goal

Make `reindex_file` operate only on an existing, indexable file. It must not
remove all indexed records merely because the target is missing or no longer
indexable. File-level removal belongs exclusively to
`delete_file_from_index`.

A successful reindex still removes obsolete chunk IDs for the same file after
the replacement chunks have been written.

## Current state

`reindex_single_file` currently returns `deleted` and calls
`delete_chunks_for_file` when the target is missing, returns
`removed_unindexable` and deletes its chunks when eligibility fails, and also
deletes when `FileNotFoundError` occurs during preparation. The MCP description
advertises this implicit cleanup.

This conflicts with the agreed inspect-then-mutate lifecycle:

1. `get_index_status` reports required actions.
2. `reindex_file` replaces an existing eligible file.
3. `delete_file_from_index` explicitly removes one indexed path.

## Result contract

Expected filesystem states should be structured results rather than
`ToolError`s:

```json
{
  "status": "file_not_found",
  "relative_path": "src/module.py"
}
```

```json
{
  "status": "not_indexable",
  "relative_path": "assets/image.png",
  "reason": "unsupported file type: image.png"
}
```

Keep `reindexed` and the existing retryable `hash_failed` outcome.
`ReindexResult` becomes:

```text
ReindexedResult | FileNotFoundResult | NotIndexableResult | HashFailedResult
```

`DeletedResult` remains available for `delete_file_from_index`, but leaves the
reindex union. Remove `RemovedUnindexableResult` after no callers remain.

Invalid arguments, paths outside the repository, an uninitialized index, and a
corrupted index remain MCP errors. Unexpected read, permission, storage, and
programming failures remain visible rather than being converted into cleanup.

## Implementation

### `src/codebase_indexer/reindexer.py`

- Remove `_deleted_result` and every call to `delete_chunks_for_file`.
- Resolve and normalize the target path as today.
- Return `file_not_found` without store access if the target is missing.
- Return `not_indexable` without store access if `should_index_file` rejects
  the existing target.
- Convert `FileNotFoundError` during eligibility checking, hashing, or chunking
  into `file_not_found`, again without store access.
- Keep `FileChangedDuringHashingError` mapped to `hash_failed`.
- Preserve successful replacement ordering:
  1. Prepare the hash and chunks.
  2. Read the previous chunk IDs.
  3. Upsert the current chunks.
  4. Delete only previous IDs absent from the new ID set.
- Preserve empty-file behavior: an existing empty eligible file is successfully
  reindexed and any obsolete chunks are removed.
- Update the module documentation to distinguish obsolete-chunk cleanup from
  file-level deletion.

### `src/codebase_indexer/results.py`

- Add `FileNotFoundResult` and `file_not_found_result`.
- Add `NotIndexableResult` and `not_indexable_result`.
- Update `ReindexResult` and `__all__`.
- Retain `DeletedResult` and `deleted_result` for the deletion tool.
- Remove `RemovedUnindexableResult` and its constructor once unused.

### `src/codebase_indexer/server.py`

Revise the tool description to say that `reindex_file` is for created, edited,
or overwritten files that currently exist and are indexable. Missing and
unindexable targets are reported without mutation. Direct callers to
`delete_file_from_index` for deleted paths, old rename paths, and files that
have become unindexable.

## Failure and race behavior

| Condition | Outcome | Store mutation |
| --- | --- | --- |
| Missing before preparation | `file_not_found` | None |
| Disappears during preparation | `file_not_found` | None |
| Existing but ineligible | `not_indexable` | None |
| Changes during hashing | retryable `hash_failed` | None |
| Permission or read error | Exception | None |
| Upsert failure | Exception | Old chunks remain |
| Obsolete-ID deletion failure | Exception | Old and new chunks may coexist |
| Successful eligible reindex | `reindexed` | Replace current representation |

A final existence check before writing would only narrow, not eliminate, the
filesystem race. Do not add locking or retry infrastructure in v0; a later
`get_index_status` call reports subsequent disappearance.

## Tests

### Reindex orchestration

- Missing targets return `file_not_found` with no store events.
- Unindexable targets return `not_indexable` with the eligibility reason and no
  store events.
- Disappearance during eligibility checking, hashing, or chunking returns
  `file_not_found` without mutation.
- Existing eligible files still upsert before obsolete-ID deletion.
- Empty eligible files still remove obsolete chunks.
- Unchanged reindexing remains idempotent.
- Hash-change detection and preparation failures preserve old chunks.
- Upsert failures preserve old chunks.
- Obsolete-ID deletion failures remain visible and can be repaired by retrying.
- Paths outside the repository fail before store access.
- Remove `delete_chunks_for_file` from the fake reindex store so accidental
  file-level deletion fails tests immediately.

### Results and MCP boundary

- Test exact `file_not_found` and `not_indexable` dictionaries.
- Update result-union and status coverage.
- Retain `deleted_result` tests for the deletion tool.
- Add MCP dispatch coverage for structured missing and unindexable outcomes.
- Preserve argument, repository, index-state, and unexpected-error tests.

Run:

```bash
pipenv run pytest tests/test_results.py tests/test_reindexer.py tests/test_server.py -k reindex
pipenv run pytest
```

## Documentation

- Update `docs/FUNCTIONAL_SPEC.md` to replace the implicit deletion outcomes
  and revise the file-change rules.
- Update `docs/ARCHITECTURE.md` with the strict status/reindex/delete boundary.
- Keep Step 5 as historical documentation; do not rewrite it as though the
  original decision was never implemented.

## Non-goals

- Implementing deletion or status reporting in this step.
- Batch reindexing or rename detection.
- Automatic cleanup, watchers, retries, locking, or transactions.
- Changing chunk identity or chunking rules.

## Decisions

- Missing and unindexable targets use structured results because they are
  expected, actionable states.
- Results do not include `suggested_action`; `get_index_status` owns action
  reporting.
- `file_not_found` is not labeled retryable because an intentional deletion and
  a concurrent disappearance cannot be distinguished reliably.

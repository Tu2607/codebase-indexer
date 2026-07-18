# Plan: Close Index Stores and Implement `remove_index`

## Goal

Add an explicit, user-approved MCP tool that removes a repository's complete
local index store. Recreating the index remains the sole responsibility of the
existing `index_repo` tool:

```text
remove_index(repo_path, confirm=true)
index_repo(repo_path)
```

The tool may remove any existing index, healthy or corrupted. It does not try
to diagnose corruption, rebuild content, or call another MCP tool.

As a prerequisite, close every ChromaDB client after each index-backed MCP
operation. This prevents cached Chroma systems and SQLite resources from
remaining attached to a deleted index path when `index_repo` recreates it in
the same MCP server process.

## Current state

`IndexStore` creates a Chroma `PersistentClient`, but exposes no close method.
The implemented MCP handlers open stores without releasing their clients after
returning or raising. Chroma shares persistent systems by index path and uses
reference counting; its public `Client.close()` method releases SQLite and
other resources when the final client closes.

The functional specification currently reserves a future `rebuild_index`
operation for corrupted-index recovery. That larger tool is no longer planned.
Recovery will instead compose two explicit operations: remove the old store,
then initialize a new one.

## Public contract

```text
remove_index(repo_path: str, confirm: bool = False) -> dict
```

Successful result:

```json
{
  "status": "removed",
  "repo_path": "/absolute/repository",
  "index_path": "/absolute/repository/.codebase-index"
}
```

Rules:

- `repo_path` is required and must resolve to an existing directory.
- `confirm` must be explicitly `true`; otherwise return a `ToolError` before
  inspecting or modifying the index path.
- The repository-local `.codebase-index` path must exist and be a real
  directory.
- Refuse a symlinked `.codebase-index` path, even when its target is inside the
  repository.
- Remove the entire directory recursively, including healthy, corrupted,
  incomplete, or otherwise unusable contents.
- If the index path is absent, return a `ToolError` stating that there is no
  index to remove. Do not redirect or automatically call `index_repo`.
- Never create a new index, walk repository files, or invoke `index_repo` as a
  side effect.
- Files outside `.codebase-index` must never be touched.

The MCP description must instruct the calling LLM to obtain explicit user
approval before passing `confirm=true`. The Boolean gate supplements that
instruction and prevents accidental calls that omit confirmation.

## Proposed design

### Chroma client lifecycle

Extend `IndexStore` with an idempotent close operation:

```text
IndexStore.close() -> None
```

- Initialize an internal closed flag for both `__init__` and `open_existing`
  construction paths.
- On the first call, invoke `self._client.close()` and mark the store closed.
- Later calls are no-ops.
- Optionally implement `__enter__` and `__exit__` only if they simplify all
  call sites without complicating tests; the required contract is `close()`.

Prevent constructor-path leaks:

- If `get_or_create_collection` fails after `PersistentClient` succeeds in
  `IndexStore.__init__`, close the client before propagating the failure.
- If `get_collection` fails after client creation in `open_existing`, close the
  client before translating or propagating the failure.
- If `PersistentClient` itself fails, there is no client to close.

Update every implemented index-backed server handler to close its store in a
`finally` block on success and failure:

- `index_repo`
- `reindex_file`
- `delete_file_from_index`
- `get_index_status`

The store remains open for the full synchronous orchestration call and closes
only after its result or exception is determined. `search_repo_context` must
follow the same lifecycle when it is implemented.

Do not call Chroma's global `clear_system_cache()`: it is process-wide, may
affect other repositories, and does not express ownership of one store. Use the
public per-client `close()` API.

### Index directory removal

Keep index-directory lifecycle behavior in `index_store.py`, alongside index
creation and opening. Add a class or static operation such as:

```text
IndexStore.remove_index(repo_path) -> Path
```

It should:

1. Resolve and validate the repository using the existing repository rule.
2. Construct exactly `resolved_repo_path / DEFAULT_INDEX_DIR_NAME`.
3. Inspect the path without following its final symlink.
4. Raise a dedicated or clear `ValueError` when the path is absent, a symlink,
   or not a directory.
5. Recursively remove that exact directory with `shutil.rmtree`.
6. Return the removed absolute index path for result construction.

The operation must not instantiate a Chroma client. Correct client cleanup is
provided by the server lifecycle change, and removal must also work when a
corrupted store cannot be opened.

No server-side concurrency or per-repository locking is added in v0. The tool
contract requires callers not to run removal concurrently with another
operation on the same repository.

### Result contract

Add `RemovedIndexResult` and `removed_index_result` in `results.py`:

```text
RemovedIndexResult = {
    status: Literal["removed"],
    repo_path: str,
    index_path: str,
}
```

Keep the result a plain JSON-friendly dictionary and add it to the public
result surface.

### MCP boundary

Register `remove_index` in `server.py`.

Handler order:

1. Reject unless `confirm is True`.
2. Validate `repo_path` using `validate_repo_path`.
3. Delegate directory removal to `IndexStore.remove_index`.
4. Translate expected validation and removal-state failures into `ToolError`.
5. Return `removed_index_result`.

Unexpected filesystem failures, such as permission or I/O errors during
recursive removal, should remain visible and must not be reported as success.
The handler never opens a store and never calls `index_repository` or
`index_repo`.

## Failure behavior

| Condition | Behavior |
| --- | --- |
| `confirm` omitted or false | `ToolError`; do not inspect or mutate index path |
| Invalid repository path | `ToolError`; no mutation |
| Index directory absent | `ToolError`: no index exists to remove |
| Index path is a symlink | `ToolError`; preserve link and target |
| Index path is not a directory | `ToolError`; preserve path |
| Healthy index exists | Remove complete index directory |
| Corrupted or incomplete index exists | Remove complete index directory |
| Recursive deletion fails | Surface failure; never return `removed` |
| Later `index_repo` partially fails | Retain partial new index and return its structured partial-failure result |

Removal is intentionally not transactional. Once confirmed, a failure may
leave a partially removed directory. Retrying `remove_index(confirm=true)` is
the recovery path while the directory still exists. If it is already absent,
the caller may explicitly choose whether to run `index_repo`.

## Tests

### `tests/test_index_store.py`

Client lifecycle:

- `close()` calls the Chroma client's public `close()` exactly once.
- Repeated `close()` calls are safe no-ops.
- `__init__` closes a created client if collection creation fails.
- `open_existing` closes a created client when collection lookup fails.
- Successful stores remain usable until explicitly closed.

Index removal:

- Removes the exact repository-local index directory and all nested contents.
- Accepts healthy, corrupted, and incomplete directory contents without
  opening ChromaDB.
- Returns the removed absolute index path.
- Rejects an absent index path.
- Rejects a symlink and preserves both the link and target.
- Rejects a non-directory path.
- Propagates recursive deletion failures.
- Does not touch similarly named paths or other repository files.

### `tests/test_server.py`

Lifecycle coverage:

- Each implemented index-backed tool closes its store after success.
- Each tool closes its store when its orchestrator raises.
- `index_repo` closes both an opened healthy store and a newly created store.
- Expected MCP error translation still occurs before the store is available
  and therefore requires no close.

`remove_index` coverage:

- Requires `confirm=true` before repository validation or removal.
- Validates `repo_path` and delegates to the store removal operation.
- Returns the exact `removed` result.
- Converts expected absent/symlink/non-directory errors to `ToolError`.
- Does not swallow unexpected filesystem failures.
- Public FastMCP signature includes `repo_path` and `confirm=False`.

### Integration coverage

Add a local FastMCP test for the critical same-process workflow:

1. Create and use an index so a Chroma client is active during a tool call.
2. Confirm that the tool call closes its store.
3. Call `remove_index(confirm=true)`.
4. Verify `.codebase-index` is absent.
5. Call `index_repo` explicitly in the same process.
6. Verify a fresh index is created and old records are absent.

Use an empty or otherwise embedding-free repository fixture so the test remains
local and network-independent.

### Results and documentation tests

- Test the exact `RemovedIndexResult` dictionary shape.
- Update the result public-surface and unique-status tests.
- Update tool signature/registration assertions.

Run:

```bash
pipenv run pytest tests/test_index_store.py tests/test_results.py tests/test_server.py -k "close or remove_index"
pipenv run pytest
```

## Documentation

- Replace the reserved `rebuild_index` entry in `docs/FUNCTIONAL_SPEC.md` with
  implemented/planned `remove_index` according to implementation state.
- Document the explicit recovery sequence:

  ```text
  remove_index(repo_path, confirm=true)
  index_repo(repo_path)
  ```

- State that removal is allowed for any existing index and always requires
  prior user approval.
- Replace errors that say to remove `.codebase-index` manually or wait for
  `rebuild_index` with guidance to call `remove_index` after approval.
- Update `docs/ARCHITECTURE.md` with explicit Chroma client ownership and close
  rules.
- Keep earlier step files as historical records; do not rewrite their original
  decisions.

## Non-goals

- Detecting or classifying index corruption before removal.
- Automatically chaining removal and initialization.
- Rebuilding inside `remove_index`.
- Preserving, backing up, or atomically swapping the old index.
- Automatic retries or rollback after filesystem deletion failures.
- Removing repository source files.
- Global Chroma cache clearing.
- Cross-process coordination, file locking, or concurrent-operation support.

## Acceptance criteria

- No implemented index-backed MCP operation leaves its `IndexStore` client
  open after returning or raising.
- `remove_index` cannot mutate the filesystem without explicit
  `confirm=true`.
- Only the exact non-symlinked `.codebase-index` directory inside the validated
  repository can be removed.
- Healthy, corrupted, and incomplete existing indexes can all be removed.
- An absent index produces an error and is never initialized implicitly.
- `remove_index` followed by a separate `index_repo` call works in the same MCP
  server process.
- All focused and full tests pass without network access.

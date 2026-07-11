# Spec: reindex_file MCP Tool (Step 5)

## Problem Statement

The codebase indexer has scaffolded MCP tools and foundational modules (hashing, chunking, ChromaDB storage), but none of them are wired together into a working end-to-end path. `reindex_file` is the narrowest useful vertical slice — it touches every layer (path resolution, indexability check, hashing, chunking, chunk CRUD, MCP interface) for exactly one file. Implementing it validates the integration before broader tools like `index_repo` add multi-file orchestration on top.

## Scope

### In Scope

- Implement `reindex_file(repo_path: str, file_path: str) -> dict` as a working MCP tool.
- Add `file_finder.py` with a single-file indexability helper.
- Add chunk CRUD methods to `IndexStore` (delete by file, upsert, get IDs).
- Add `IndexNotInitializedError` and an `open_existing()` construction path on `IndexStore` that refuses to create an index or collection.
- Add a side-effect-free index initialization check (no directory or collection created).
- Add a testable orchestration function outside `server.py`.
- Update `AGENTS.md` tool contracts so all index-backed tools accept `repo_path` (implement only `reindex_file`).
- Update the `reindex_file` MCP tool signature in `server.py` to include `repo_path`.
- Accept `embedding_function` via dependency injection on `open_existing()` for network-free testing.
- Focused tests covering all defined result statuses and edge cases.

### Out of Scope

- `index_repo`, `delete_file_from_index`, `search_repo_context`, `get_index_status` — remain scaffolded stubs.
- Recursive repository walking or whole-repository reindex.
- Creating an index or Chroma collection (that is `index_repo`'s job).
- `.git` discovery or upward filesystem walk — `repo_path` is always explicit.
- Pending-reindex state tracking or internal retry on `FileChangedDuringHashingError`.
- Background auto-reindexing or file watchers.
- Staleness detection on search results (belongs to `search_repo_context`).
- General-purpose public CRUD API on `IndexStore` — the methods added here are implementation details for file-level reindexing.

## Requirements

### R1 — New module: `file_finder.py`

1. Export `should_index_file(file_path: Path, repo_path: Path) -> tuple[bool, str | None]`.
2. `file_path` and `repo_path` must already be resolved absolute paths. The function does not resolve them.
3. Check order and failure reasons (first failing check wins):
   a. **Regular file** — `stat()` the path; if not a regular file (symlink to non-regular, FIFO, device, etc.), return `(False, "not a regular file")`.
   b. **Skipped directory** — compute relative path from `repo_path`; if any *parent directory component* is in `SKIP_DIRECTORIES`, return `(False, "inside skipped directory: {component}")`.
   c. **Extension / filename allowlist** — if the file's suffix is not in `INDEX_EXTENSIONS` and the file's name is not in `INDEX_FILENAMES`, return `(False, "unsupported file type: {name}")`.
   d. **File size** — if `stat().st_size > MAX_FILE_SIZE_BYTES`, return `(False, "file too large: {size} bytes, limit {MAX_FILE_SIZE_BYTES} bytes")`.
4. If all checks pass, return `(True, None)`.
5. The function must not read file contents. It uses only `stat()` and path string operations.
6. Add to `__all__`.

### R2 — `IndexStore` modifications in `index_store.py`

7. Add `IndexNotInitializedError(ValueError)` — raised when reindex_file is called against a repo that has never been indexed.

8. Add a static or class method `is_initialized(repo_path: Path) -> bool`:
   - Returns `True` if `{resolved_repo_path}/.codebase-index/chroma.sqlite3` exists as a file. Checking only the directory is insufficient because constructing `PersistentClient` in an empty directory writes Chroma persistence state before a missing-collection error can be raised.
   - **Side-effect-free**: does not create directories, clients, or collections.

9. Add classmethod `open_existing(cls, repo_path: str | os.PathLike, *, embedding_function=None) -> IndexStore`:
   - Resolve and validate `repo_path` (must be existing directory).
   - Check `is_initialized()` before constructing `PersistentClient` — if `False`, raise `IndexNotInitializedError` with a message mentioning `index_repo`. This keeps the missing-index failure path free of Chroma writes.
   - Create `PersistentClient` (safe because directory exists).
   - Call `client.get_collection(name=DEFAULT_COLLECTION_NAME)` when no embedding function is injected. Chroma 1.5.9 selects its default embedding function only when the argument is omitted; explicitly passing `None` disables embedding. When a test injects an embedding function, pass it explicitly. If the collection doesn't exist, catch `chromadb.errors.NotFoundError` and raise `IndexNotInitializedError`.
   - Construct and return an `IndexStore` instance, bypassing the `get_or_create_collection` path in `__init__`. Use `cls.__new__(cls)` or a private `_from_parts` pattern — do not add conditional flags to `__init__`.
   - The existing `__init__` (which creates-if-missing) stays unchanged for future use by `index_repo`.

10. Add `get_chunk_ids_for_file(self, relative_path: str) -> list[str]`:
    - Query `self._collection.get(where={"relative_path": relative_path}, include=[])`.
    - Return `result["ids"]`.
    - Returns empty list if no chunks exist for this path.

11. Add `upsert_chunks(self, chunks: list[TextChunk]) -> None`:
    - If `chunks` is empty, return immediately (no Chroma call).
    - Call `self._collection.upsert(ids=[c.id for c in chunks], documents=[c.document for c in chunks], metadatas=[c.metadata for c in chunks])`.
    - Chroma's default embedding function generates embeddings from the document text.

12. Add `delete_chunks_by_ids(self, ids: list[str]) -> None`:
    - If `ids` is empty, return immediately.
    - Call `self._collection.delete(ids=ids)`.

13. Add convenience method `delete_chunks_for_file(self, relative_path: str) -> int`:
    - Call `get_chunk_ids_for_file(relative_path)` to get matching IDs.
    - Call `delete_chunks_by_ids(ids)` to delete them.
    - Return `len(ids)` — the count of chunks that existed before deletion.
    - This produces a predictable deletion count despite Chroma's `delete()` returning no count, because the count is determined by the `get` query before the delete call.

### R3 — Path resolution utility

14. The orchestration function must normalize `file_path` before any other work:
    - If `file_path` is absolute: `Path(file_path).resolve()`.
    - If `file_path` is relative: `(Path(repo_path).resolve() / file_path).resolve()`.
    - Compute `relative_path = resolved_file.relative_to(resolved_repo).as_posix()`. If this raises `ValueError`, the path is outside the repository — raise a `ValueError` that includes both resolved paths. Reject `relative_path == "."` because a repository root is not an indexable file path.
    - This normalization must work for non-existent files (deleted file case). `Path.resolve()` with `strict=False` (default) handles this.
    - Implement this as `path_utils.resolve_repo_file_path(repo_path, file_path) -> tuple[Path, Path, str]` so `reindex_file` and future single-file MCP tools share one containment rule. The tuple contains the resolved repository path, resolved file path, and POSIX relative path.

### R4 — Orchestration function

15. Create a new module `reindexer.py` with function `reindex_single_file(store: IndexStore, file_path: str, repo_path: Path) -> dict`:
    - `store` is an already-opened `IndexStore` (the caller handles initialization checks).
    - `repo_path` is an already-resolved `Path`.
    - The function is the testable core — no FastMCP dependency.

16. Orchestration flow:
    a. **Normalize** `file_path` against `repo_path` → `(resolved_path, relative_path)`. Raise `ValueError` if outside repo.
    b. **Missing file**: if `resolved_path` does not exist (`not resolved_path.exists()`), delete existing chunks for `relative_path` and return `deleted` result.
    c. **Unindexable file**: call `should_index_file(resolved_path, repo_path)`. If not indexable, delete existing chunks and return `removed_unindexable` result with the reason.
    d. **Hash**: call `hash_file(resolved_path)`. On `FileChangedDuringHashingError`, return `hash_failed` result immediately — do not touch the index.
    e. **Chunk**: call `chunk_by_lines(resolved_path, repo_path=repo_path, file_hash=file_hash)`.
    f. **Get old IDs**: call `store.get_chunk_ids_for_file(relative_path)`.
    g. **Upsert new chunks**: call `store.upsert_chunks(new_chunks)`. New data is written before old data is removed.
    h. **Delete stale IDs**: compute `stale_ids = [id for id in old_ids if id not in new_id_set]`. Call `store.delete_chunks_by_ids(stale_ids)`.
    i. **Return** `reindexed` result.

17. **Safe replacement ordering and failure behavior**:
    - New chunks are upserted (step g) before stale chunks are deleted (step h). This ensures that if upsert succeeds but deletion fails, the index has duplicates (old + new) but no data loss. The next `reindex_file` call will clean up.
    - If upsert fails, old chunks remain intact. The index is stale but not corrupt.
    - If the file hasn't changed, chunk IDs are identical (they embed the file hash). Upsert is idempotent, and `stale_ids` is empty. This is a safe no-op reindex.
    - This ordering guarantees: the index is never in a state where a file's data has been removed without replacement, unless the file itself is gone or unindexable.

### R5 — Result status dictionaries

18. All results include `"status"` as the first semantic key. Exact shapes:

**`reindexed`** — file exists, is indexable, successfully hashed and chunked:
```python
{
    "status": "reindexed",
    "relative_path": "src/foo.py",
    "file_hash": "abc123...",
    "chunks_added": 5,
    "chunks_removed": 3,
}
```

`chunks_added` counts chunk IDs that were not already present for the file.

**`deleted`** — file does not exist at the resolved path:
```python
{
    "status": "deleted",
    "relative_path": "src/foo.py",
    "chunks_removed": 3,  # 0 is valid (file was never indexed)
}
```

**`removed_unindexable`** — file exists but fails indexability checks:
```python
{
    "status": "removed_unindexable",
    "relative_path": "src/foo.xyz",
    "reason": "unsupported file type: foo.xyz",
    "chunks_removed": 0,
}
```

**`hash_failed`** — `FileChangedDuringHashingError` caught, index left unchanged:
```python
{
    "status": "hash_failed",
    "relative_path": "src/foo.py",
    "retryable": True,
    "message": "File changed during hashing; retry after the write completes",
}
```

19. Results remain plain dictionaries at runtime. Define their four shapes as `TypedDict` contracts and construct them through small builder functions in `results.py`; do not introduce dataclass or enum wrappers.

### R6 — MCP tool in `server.py`

20. Change the `reindex_file` MCP tool signature to `reindex_file(repo_path: str, file_path: str) -> dict[str, object]`.

21. Implementation in `server.py`:
    a. Validate `repo_path` through `path_utils.validate_repo_path`; convert its `ValueError` to `ToolError` at the MCP boundary.
    b. Open `IndexStore.open_existing(repo_path)`. This performs the side-effect-free existing-index check and raises `IndexNotInitializedError` when `index_repo` has not initialized the repository.
    c. Call `reindex_single_file(store, file_path, store.repo_path)`.
    d. Return the result dict.
    e. Catch `IndexNotInitializedError` and other `ValueError` instances from repository/path validation, and raise `ToolError`.

22. Update the MCP tool description to:
    > "Re-index one file after it has been edited, created, or overwritten. Call this after editing any indexed file. If the file was deleted, its chunks are removed from the index. Requires an existing index created by index_repo."

23. Update the remaining scaffolded tool signatures to accept `repo_path` where specified by AGENTS.md (change parameter lists only — implementations remain `_raise_not_implemented`). Specifically:
    - `reindex_file(repo_path: str, file_path: str)` — implemented.
    - `delete_file_from_index(repo_path: str, file_path: str)` — stub.
    - `search_repo_context(repo_path: str, query: str, ...)` — stub.
    - `index_repo` already has `repo_path`.
    - `get_index_status` already has `repo_path`.

### R7 — AGENTS.md updates

24. Update the `reindex_file` tool contract in AGENTS.md to show `reindex_file(repo_path: str, file_path: str) -> dict` and note that `repo_path` must be passed explicitly.

25. Update `delete_file_from_index` and `search_repo_context` contracts to include `repo_path` parameter (document the intended signature, not the implementation — these are stubs).

26. Add a note under MCP Tools: "All index-backed tools require `repo_path` to be passed explicitly. The server does not discover or infer the repository path."

### R8 — Embedding function injection for tests

27. `IndexStore.open_existing()` accepts an optional `embedding_function` keyword argument. When it is `None`, omit the argument from `get_collection` so Chroma uses its default. Tests pass a fake explicitly.
28. Tests pass a deterministic fake embedding function (e.g., `lambda docs: [[0.0] * 384 for _ in docs]`) to avoid ONNX model downloads and network calls.
29. Tests that only use `delete_chunks_for_file`, `get_chunk_ids_for_file`, or `delete_chunks_by_ids` (no upsert with document text) can use the existing pattern from `test_index_store.py`: provide explicit `embeddings=` directly to Chroma's API for fixture setup, which bypasses the embedding function entirely.
30. Tests that exercise `upsert_chunks` (which calls `collection.upsert` without explicit embeddings) must inject the fake embedding function.

## Acceptance Criteria

- [ ] `reindex_file(repo_path, file_path)` is callable as an MCP tool via FastMCP.
- [ ] Calling `reindex_file` on a repo with no `.codebase-index` directory returns a `ToolError` mentioning `index_repo`.
- [ ] Missing file: removes chunks for the normalized relative path, returns `{"status": "deleted", ...}` with accurate `chunks_removed`.
- [ ] Existing file with unsupported extension: removes old chunks, returns `{"status": "removed_unindexable", ...}` with reason.
- [ ] Existing file over MAX_FILE_SIZE_BYTES: returns `removed_unindexable` with size reason.
- [ ] Existing file in a skipped directory path: returns `removed_unindexable`.
- [ ] Non-regular file (e.g., FIFO): returns `removed_unindexable`.
- [ ] Indexable file: hashes, chunks, upserts new chunks, deletes stale chunks, returns `{"status": "reindexed", ...}` with `file_hash`, `chunks_added`, `chunks_removed`.
- [ ] Empty indexable file: returns `reindexed` with `chunks_added: 0`.
- [ ] `FileChangedDuringHashingError`: returns `{"status": "hash_failed", "retryable": True}`, index unchanged.
- [ ] File path outside repository: raises `ToolError` / `ValueError`.
- [ ] Relative `file_path` resolved against `repo_path`, not CWD.
- [ ] Re-running `reindex_file` on an unchanged file is idempotent (chunk IDs are stable).
- [ ] New chunks are written before stale chunks are deleted (safe ordering).
- [ ] All tests pass without network access or ONNX model downloads.
- [ ] `AGENTS.md` documents `repo_path` on all index-backed tools.
- [ ] `pipenv run pytest` passes with all new and existing tests.

## Task Order

1. **`file_finder.py`** — Create the module with `should_index_file`. Add `tests/test_file_finder.py`. Run tests.
2. **`IndexStore` additions** — Add `IndexNotInitializedError`, `is_initialized()`, `open_existing()`, `get_chunk_ids_for_file()`, `upsert_chunks()`, `delete_chunks_by_ids()`, `delete_chunks_for_file()`. Add tests in `tests/test_index_store.py`. Run tests.
3. **`reindexer.py`** — Create the module with `reindex_single_file` and path normalization helper. Add `tests/test_reindexer.py`. Run tests.
4. **`server.py`** — Wire `reindex_file` MCP tool to the orchestration function. Update remaining tool stubs to accept `repo_path`. Run tests.
5. **`AGENTS.md`** — Update tool contracts for `repo_path`.
6. **Full test suite** — Run `pipenv run pytest` and verify all tests pass, including pre-existing ones.

## Test Strategy

All tests use `tmp_path` fixtures and avoid network calls. Tests that exercise `upsert_chunks` inject a fake embedding function. Tests that only set up fixture data in Chroma use explicit `embeddings=` via the collection API.

### `tests/test_file_finder.py` (~10 tests)
- Regular `.py` file → indexable.
- File with unsupported extension → not indexable, reason mentions file type.
- File with exact-match name (e.g., `Dockerfile`) and no extension → indexable.
- File over `MAX_FILE_SIZE_BYTES` → not indexable, reason mentions size.
- File inside a skipped directory (`node_modules/foo.js`) → not indexable, reason mentions directory.
- Non-regular file (use `os.mkfifo` where available, skip on unsupported platforms) → not indexable.
- Symlink to a regular indexable file → indexable.
- File at repo root (no parent directories to check) → indexable if extension matches.
- Deeply nested file in a non-skipped path → indexable.
- File with name in `INDEX_FILENAMES` but also in a skipped directory → not indexable (directory check takes priority).

### `tests/test_index_store.py` (add ~10 tests)
- `is_initialized` returns `False` for a fresh directory with no `.codebase-index`.
- `is_initialized` returns `False` for an empty `.codebase-index` directory and `True` after an `IndexStore` has created Chroma's database file.
- `open_existing` raises `IndexNotInitializedError` when `.codebase-index` doesn't exist.
- `open_existing` raises `IndexNotInitializedError` when directory exists but collection doesn't (edge case — create the dir manually without Chroma).
- `open_existing` succeeds after a normal `IndexStore()` has been created.
- `upsert_chunks` adds chunks retrievable by ID.
- `upsert_chunks` with empty list is a no-op.
- `get_chunk_ids_for_file` returns matching IDs; returns empty for unknown path.
- `delete_chunks_for_file` returns count and actually removes chunks.
- `delete_chunks_for_file` returns 0 for a path with no chunks.
- `delete_chunks_by_ids` with empty list is a no-op.

### `tests/test_reindexer.py` (~10 tests)
- **Successful reindex**: create an initialized store, write a `.py` file, call `reindex_single_file` → status `reindexed`, correct `chunks_added`, `file_hash`.
- **Missing file**: file doesn't exist, pre-seed some chunks for its path → status `deleted`, `chunks_removed` matches seeded count.
- **Missing file, never indexed**: file doesn't exist, no prior chunks → status `deleted`, `chunks_removed: 0`.
- **Unsupported extension**: write a `.xyz` file → status `removed_unindexable`.
- **Oversized file**: write a file larger than `MAX_FILE_SIZE_BYTES` → status `removed_unindexable`, reason mentions size.
- **Empty file**: write an empty `.py` file → status `reindexed`, `chunks_added: 0`.
- **File outside repo**: pass a path that resolves outside `repo_path` → `ValueError`.
- **Relative path resolution**: pass `"src/foo.py"` (relative), verify it resolves against `repo_path`.
- **Hash failure**: monkeypatch `hash_file` to raise `FileChangedDuringHashingError` → status `hash_failed`, `retryable: True`, verify no chunks were modified.
- **Idempotent reindex**: call twice on the same unchanged file → second call returns `chunks_removed: 0` and same `chunks_added`.
- **Re-index after edit**: seed chunks, modify file, reindex → new hash, stale chunks removed, new chunks added.

## Open Questions

1. **`open_existing` construction pattern**: The spec recommends `cls.__new__(cls)` or a private `_from_parts` classmethod to avoid muddying `__init__`. Either pattern is acceptable; pick whichever reads more clearly. The constraint is: `__init__` must remain unchanged (it's the future `index_repo` creation path).

2. **Chroma `get_collection` exception type**: Chroma's exception for a missing collection may be `ValueError`, `InvalidCollectionException`, or vary by version. The implementation should catch the specific exception Chroma 1.x raises and wrap it in `IndexNotInitializedError`. Verify against the installed version during implementation.

3. **Symlink-to-regular-file behavior in `should_index_file`**: The spec treats symlinks that resolve to regular files as indexable (consistent with `hash_file` following symlinks). If this is undesirable, add a symlink check. Current recommendation: allow it — personal-use tool, keep it simple.

4. **`upsert_chunks` embedding dimension**: The fake embedding function in tests must return vectors matching Chroma's expected dimension. Chroma's default `all-MiniLM-L6-v2` uses 384 dimensions. The fake should return 384-dimensional vectors. If the installed Chroma version's default changes dimensions, tests will fail with a clear error — this is acceptable as a canary.

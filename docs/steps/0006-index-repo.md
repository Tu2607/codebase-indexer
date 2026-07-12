# Step 6: `index_repo(repo_path)` — Implementation Plan

## Summary

Implement `index_repo` as an initialization-only MCP tool. It creates a new ChromaDB index for a repository that has no usable index, returns `initialized` with `created=false` for a healthy existing index (no walk, no mutation), and raises a ToolError for a corrupted/unavailable index. The `force` parameter is removed from the public MCP contract. A ThreadPoolExecutor (default 7 workers) fans file preparation (hash + chunk) in bounded batches (default 32 files) into a single-threaded Chroma writer. Per-file failures are recorded without stopping the walk; if any files fail, the tool raises a ToolError with a JSON-friendly summary. Files missing during the discovery walk are counted as skipped (they were never in the index); files that were discovered as eligible but disappear or change during worker preparation are recorded as file failures for later `reindex_file` recovery.

## 1. Module Changes Overview

| Module | Change |
|---|---|
| `config.py` | Add `DEFAULT_INDEX_WORKERS = 7` and `DEFAULT_INDEX_BATCH_SIZE = 32` |
| `index_store.py` | Add `IndexCorruptedError`; update `open_existing` to raise it for DB-exists-but-collection-missing and DB-cannot-open cases |
| `file_finder.py` | Add `iter_indexable_files(repo_path)` returning eligible files + skip count; canonical-path deduplication; no symlinked directories |
| `results.py` | Add `InitializedResult` (with `created` boolean), `PartialFailureDetail`, `PartialFailureResult` TypedDicts + constructors |
| `indexer.py` (new) | Core orchestration: `index_repository(store, repo_path)` with ThreadPoolExecutor (`DEFAULT_INDEX_WORKERS`, batches of `DEFAULT_INDEX_BATCH_SIZE`) + fan-in Chroma writer |
| `server.py` | Wire `index_repo` tool: remove `force`, add gate logic, catch `IndexCorruptedError`, delegate to `indexer.index_repository` |
| `AGENTS.md` | Update `index_repo` signature (remove `force`), note initialization-only semantics |

## 2. `IndexCorruptedError` — `index_store.py`

### New exception

Add alongside `IndexNotInitializedError`:

```python
class IndexCorruptedError(ValueError):
    """Raised when a repository's index database exists but cannot be opened."""
```

Export in `__all__`: `["IndexCorruptedError", "IndexNotInitializedError", "IndexStore"]`.

### `open_existing` changes

Current behavior:
- No DB file → `IndexNotInitializedError` ✓ (keep)
- `PersistentClient(...)` fails → unhandled (propagates raw chromadb/sqlite error)
- `get_collection` raises `NotFoundError` → `IndexNotInitializedError`

New behavior:
- No DB file → `IndexNotInitializedError` (unchanged)
- `PersistentClient(...)` fails → **catch `Exception`, raise `IndexCorruptedError`** with message: `"Index database exists but cannot be opened; run rebuild_index: {resolved_repo_path}"`
- `get_collection` raises `NotFoundError` → **raise `IndexCorruptedError`** (not `IndexNotInitializedError`) with message: `"Index database exists but collection is missing; run rebuild_index: {resolved_repo_path}"`

Rationale: If the DB file exists, the index was previously created. A missing collection within an existing DB is an inconsistent/corrupted state, not an uninitialized one. `IndexNotInitializedError` ("run index_repo") is semantically wrong — `index_repo` would also refuse. The correct guidance is "run rebuild_index."

### Impact on `reindex_file`

`server.py` currently catches `IndexNotInitializedError` from `open_existing`. It must now also catch `IndexCorruptedError`:

```python
except IndexCorruptedError as exc:
    raise ToolError(str(exc)) from exc
```

This is a one-line addition in the existing except chain. The test `test_open_existing_wraps_chroma_missing_collection_error` in `test_index_store.py` must update its expected exception from `IndexNotInitializedError` to `IndexCorruptedError`.

## 3. File Discovery — `file_finder.py`

### New function: `iter_indexable_files`

```python
def iter_indexable_files(repo_path: Path) -> tuple[list[tuple[Path, str]], int]:
```

Returns `(eligible_files, skipped_count)` where each eligible file is `(resolved_file_path, relative_posix_path)`. The list is sorted by `relative_posix_path` for deterministic processing and reporting.

#### Walk behavior

- Use `os.walk(repo_path, followlinks=False)`. With `followlinks=False` (default), `os.walk` does **not** descend into symlinked directories, satisfying the "do not follow symlinked directories" requirement without additional pruning.
- Prune `SKIP_DIRECTORIES` from `dirnames` in-place (`dirnames[:] = [d for d in sorted(dirnames) if d not in SKIP_DIRECTORIES]`). Sort `dirnames` for deterministic walk order.
- For each file entry, construct `file_path = Path(dirpath) / filename`.
- Call `should_index_file(file_path, repo_path)`. If it raises `OSError` (file disappeared, permission denied, etc.), count as skipped and continue.
- If not indexable, increment `skipped_count` and continue.
- Resolve the canonical path (`file_path.resolve()`) and check against a `seen_canonical: set[Path]`. If already seen, increment `skipped_count` and continue (deduplication for in-repo file symlinks pointing to the same target).
- Add the canonical path to `seen_canonical`.
- Compute `relative_path = file_path.relative_to(repo_path).as_posix()`.
- Append `(file_path.resolve(), relative_path)` to the eligible list.

#### Notes

- The function does not read file contents, hash, or chunk. It only discovers and filters.
- `should_index_file` already enforces extension/filename allowlists, `SKIP_DIRECTORIES` on path components, regular-file check, and 300 KiB max size.
- **Discovery skip vs. file failure**: A file that is missing, unreadable, or filtered out during this walk was never in the index. It is a discovery skip — count it as skipped and continue. A file that is discovered as eligible here but disappears or changes during worker preparation (hashing/chunking in `indexer.py`) is a file failure, recorded in the failures list for later recovery with `reindex_file`.
- **Symlink policy — canonical-path deduplication**: `followlinks=False` prevents descending into symlinked directories. File symlinks that resolve inside the repository may be discovered by the walk, but canonical-path deduplication (`file_path.resolve()` against `seen_canonical`) ensures the target is indexed exactly once. No ghost path is created for the symlink alias — the duplicate is counted as skipped.

Add to `__all__`: `["iter_indexable_files", "should_index_file"]`.

## 4. Result Contracts — `results.py`

### New TypedDicts

```python
from typing import NotRequired

class InitializedResult(TypedDict):
    status: Literal["initialized"]
    repo_path: str
    index_path: str
    created: bool
    files_indexed: NotRequired[int]
    chunks_indexed: NotRequired[int]
    files_skipped: NotRequired[int]

class PartialFailureDetail(TypedDict):
    relative_path: str
    reason: str

class PartialFailureResult(TypedDict):
    status: Literal["partial_failure"]
    repo_path: str
    index_path: str
    files_indexed: int
    chunks_indexed: int
    files_skipped: int
    files_failed: int
    failures: list[PartialFailureDetail]
```

The `created` field distinguishes whether this call created and walked the index (`true`) or found a healthy existing index (`false`). Walk-count fields (`files_indexed`, `chunks_indexed`, `files_skipped`) are present only when `created=true`. They are `NotRequired` so the `created=false` path omits them cleanly rather than returning misleading zeros.

### Constructor functions

```python
def initialized_result(
    repo_path: str, index_path: str,
    *, created: bool,
    files_indexed: int = 0, chunks_indexed: int = 0, files_skipped: int = 0,
) -> InitializedResult:
    """When created=True, includes walk counts. When created=False, omits them."""

def partial_failure_result(
    repo_path: str, index_path: str,
    files_indexed: int, chunks_indexed: int, files_skipped: int,
    failures: list[PartialFailureDetail],
) -> PartialFailureResult: ...
```

The `initialized_result` constructor conditionally includes walk-count fields only when `created=True`.

### Type alias

```python
IndexRepoResult = InitializedResult
```

Note: `PartialFailureResult` is not in the alias because it is delivered via ToolError, not as a normal return value. The `partial_failure_result` constructor is used to build the JSON payload for the ToolError message. The alias is retained for forward compatibility if additional success result types are added later.

Add all new types and constructors to `__all__`.

## 5. Orchestration — `indexer.py` (new module)

### Public function

```python
def index_repository(store: IndexStore, repo_path: Path) -> InitializedResult:
```

Called after the gate in `server.py` has determined a new index is needed. `store` is a freshly created `IndexStore` (from `IndexStore.__init__`, which calls `get_or_create_collection`).

### Internal types

```python
@dataclass(frozen=True)
class _PreparedFile:
    relative_path: str
    chunks: list[TextChunk]

@dataclass(frozen=True)
class _FileFailure:
    relative_path: str
    reason: str
```

### `_prepare_file` (worker function)

```python
def _prepare_file(file_path: Path, repo_path: Path, relative_path: str) -> _PreparedFile:
```

- Calls `hash_file(file_path)` → SHA-256 hex digest.
- Calls `chunk_by_lines(file_path, repo_path=repo_path, file_hash=file_hash)` → `list[TextChunk]`.
- Returns `_PreparedFile(relative_path, chunks)`.
- Does **not** access IndexStore or Chroma.
- Does **not** catch exceptions — they propagate to the caller via `Future.result()`.

### `index_repository` flow

```
1. eligible_files, skipped_count = iter_indexable_files(repo_path)
2. If no eligible files → return initialized_result(..., created=True, files_indexed=0, chunks_indexed=0, files_skipped=skipped_count)
3. Initialize counters: files_indexed=0, chunks_indexed=0, failures=[]
4. Process files in bounded batches with ThreadPoolExecutor:
   - batch_size from config.DEFAULT_INDEX_BATCH_SIZE (default 32)
   - workers from config.DEFAULT_INDEX_WORKERS (default 7)
   - For each batch of batch_size files:
     a. Submit all batch files to executor → dict[Future, relative_path]
     b. Iterate futures via as_completed:
        - Try future.result() → PreparedFile
        - On exception: append FileFailure(relative_path, str(exc)) to failures, continue
        - Try store.upsert_chunks(prepared.chunks)
        - On exception: append FileFailure(relative_path, f"index write failed: {exc}") to failures, continue
        - Increment files_indexed and chunks_indexed
5. If failures is non-empty:
   - Sort failures by relative_path
   - Build PartialFailureResult dict
   - Raise IndexPartialFailureError(json.dumps(result_dict))
6. Return initialized_result(..., created=True, ...)
```

Exceptions in step 4b are file failures: the file was discovered as eligible by `iter_indexable_files` but failed during preparation or Chroma writing. Each failed file is recorded for later `reindex_file` recovery. This is distinct from discovery skips in step 1, which are files that were never eligible.

### Backpressure

Files are submitted in batches of `DEFAULT_INDEX_BATCH_SIZE` (32). Within each batch, at most `DEFAULT_INDEX_WORKERS` (7) file preparations run concurrently. The main thread consumes results via `as_completed` and writes each file's chunks to Chroma immediately. At any point, memory holds at most ~32 files' worth of prepared chunks (completed futures awaiting consumption) plus any being actively prepared.

A batch size of 32 bounds memory while remaining large enough to amortize ThreadPoolExecutor overhead — submitting 32 futures per batch avoids per-file executor setup costs without holding an unbounded number of prepared chunks in memory. Both `DEFAULT_INDEX_BATCH_SIZE` and `DEFAULT_INDEX_WORKERS` are centralized in `config.py` but are not exposed as public MCP parameters in v0.

This is a v0 tradeoff: a semaphore-based pipeline or queue would be more memory-optimal for very large repos, but bounded batching is simpler and sufficient for personal-use repositories.

### Chroma write serialization

All `store.upsert_chunks(...)` calls happen in the main thread, serialized by the `as_completed` iteration. Workers never access IndexStore or Chroma. This is an explicit v0 design choice because concurrent write safety has not been established.

### `IndexPartialFailureError`

A new internal exception in `indexer.py` (not exported, not shared):

```python
class IndexPartialFailureError(Exception):
    """Raised when some files failed during initial indexing."""
```

The message is the JSON-serialized `PartialFailureResult`. `server.py` catches this and converts to ToolError.

## 6. Gate Sequence — `server.py`

### `index_repo` tool

New signature (remove `force`):

```python
@mcp.tool(description=("...updated description..."))
def index_repo(repo_path: str) -> dict[str, object]:
```

Updated description:

```
"Initialize a repository index. Call this at the beginning of a session or "
"when no usable index exists. If the index already exists and is healthy, "
"returns immediately without modifying it. For updating individual files "
"after edits, use reindex_file instead."
```

### Gate logic

```python
def index_repo(repo_path: str) -> dict[str, object]:
    # 1. Validate
    try:
        resolved_repo_path = validate_repo_path(repo_path)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    # 2. Open the existing index as the authoritative health check.
    try:
        store = IndexStore.open_existing(resolved_repo_path)
    except IndexNotInitializedError:
        # No database or collection exists yet; create the initial store.
        try:
            store = IndexStore(resolved_repo_path)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
    except IndexCorruptedError as exc:
        raise ToolError(str(exc)) from exc
    else:
        # Healthy existing index — no walk, no mutation.
        return initialized_result(
            str(resolved_repo_path), str(store.index_dir),
            created=False,
        )

    # 3. Perform initial walk
    try:
        return index_repository(store, resolved_repo_path)
    except IndexPartialFailureError as exc:
        raise ToolError(str(exc)) from exc
```

### Key decisions in the gate

| State | Behavior |
|---|---|
| No database or collection can be opened | Create `IndexStore` (creates dir + collection), walk repo |
| DB exists, collection opens | Return `initialized` with `created=false`, no walk, no mutation |
| DB exists, collection missing | `IndexCorruptedError` → ToolError: "run rebuild_index" |
| DB exists, `PersistentClient` fails | `IndexCorruptedError` → ToolError: "run rebuild_index" |
| Store disappears before creation | `IndexStore.__init__` uses `get_or_create_collection`, which is idempotent — safe |

### `reindex_file` update

Add `IndexCorruptedError` to the import and except chain:

```python
from .index_store import IndexCorruptedError, IndexNotInitializedError, IndexStore

...

    try:
        store = IndexStore.open_existing(resolved_repo_path)
    except IndexNotInitializedError as exc:
        raise ToolError(str(exc)) from exc
    except IndexCorruptedError as exc:
        raise ToolError(str(exc)) from exc
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
```

## 7. Error Handling Summary

### Per-file errors during preparation/writing (non-fatal)

These errors apply to files that were discovered as eligible by `iter_indexable_files` but fail during worker preparation (hashing/chunking) or Chroma writing. Each is recorded as a file failure for later `reindex_file` recovery. Files that are missing or unreadable during the discovery walk are counted as discovery skips by `iter_indexable_files` and never reach this phase.

| Error | Source | Handling |
|---|---|---|
| `FileNotFoundError` | hash_file, chunk_by_lines | Record failure, continue |
| `FileChangedDuringHashingError` | hash_file | Record failure, continue |
| `PermissionError` | hash_file, chunk_by_lines | Record failure, continue |
| `OSError` (other) | hash_file, chunk_by_lines | Record failure, continue |
| `UnicodeDecodeError` | chunk_by_lines | Shouldn't happen (uses `errors="replace"`) |
| Chroma upsert failure | store.upsert_chunks | Record failure, continue |

All per-file errors are caught in the `index_repository` batch loop. Failed files are recorded in the `failures` list. Successfully indexed files remain persisted. After all files are processed, if `failures` is non-empty, raise `IndexPartialFailureError`.

### Collection-level errors (fatal, stop before walking)

| Error | Source | Handling |
|---|---|---|
| `IndexCorruptedError` | open_existing | ToolError: "run rebuild_index" |
| `IndexNotInitializedError` | open_existing | Create a new store and perform the initial walk |
| `ValueError` (bad repo_path) | validate_repo_path | ToolError |

### ToolError payloads

**Corruption/unavailable:**
```
"Index database exists but collection is missing; run rebuild_index: /path/to/repo"
```

**Partial failure** (JSON in ToolError message):
```json
{
  "status": "partial_failure",
  "repo_path": "/path/to/repo",
  "index_path": "/path/to/repo/.codebase-index",
  "files_indexed": 47,
  "chunks_indexed": 312,
  "files_skipped": 15,
  "files_failed": 3,
  "failures": [
    {"relative_path": "src/broken.py", "reason": "File changed during hashing"},
    {"relative_path": "src/locked.py", "reason": "[Errno 13] Permission denied"},
    {"relative_path": "src/vanished.py", "reason": "index write failed: embedding error"}
  ]
}
```

Failures are sorted by `relative_path` for determinism regardless of worker completion order.

## 8. AGENTS.md Updates

- Update `index_repo` signature: remove `force` parameter.
- Remove bullet about "If force is false and the file hash has not changed, skip re-indexing."
- Add note: `index_repo` is initialization-only; it does not rewalk or refresh a healthy existing index.
- Clarify: if the index is corrupted, `index_repo` raises an error and does not attempt recovery.

## 9. Test Plan

All tests are network-free. Chroma tests use `FakeEmbeddingFunction` (existing pattern from `test_index_store.py`) or mock IndexStore with a fake (existing pattern from `test_reindexer.py`).

### `test_file_finder.py` — `iter_indexable_files`

| Test | What it verifies |
|---|---|
| Discovers eligible files from a multi-directory repo | Basic walk with .py, .js, .md files returns expected relative paths |
| Returns empty list for repo with no eligible files | Only .png, .exe files → `([], N)` |
| Skips SKIP_DIRECTORIES | Files under `node_modules/`, `__pycache__/` etc. are counted as skipped |
| Does not follow symlinked directories | Symlink to a directory with eligible files → those files not discovered |
| Deduplicates in-repo file symlinks | `link.py -> real.py` both resolve to same canonical path → only one in eligible list, other counted as skipped |
| Returns sorted by relative_path | Discovered files are in lexicographic order |
| Counts OSError during filtering as skipped | `should_index_file` raises `OSError` → file counted as skipped, walk continues |
| Respects max file size | File > 300 KiB is counted as skipped |
| Handles empty repository | Empty directory → `([], 0)` |

### `test_indexer.py` — `index_repository`

Uses a `FakeIndexStore` (similar pattern to `test_reindexer.py`) to avoid Chroma/embedding dependencies.

| Test | What it verifies |
|---|---|
| Indexes all eligible files and returns correct counts | `initialized` result with `created=true` and accurate `files_indexed`, `chunks_indexed`, `files_skipped` |
| Empty repo returns initialized with zero counts | No eligible files → `created=true`, `files_indexed=0, chunks_indexed=0` |
| File disappearing during preparation is a file failure | Monkeypatch `hash_file` to raise `FileNotFoundError` for one file → recorded in failures list (a file failure, not a discovery skip), others succeed |
| File changing during hashing is recorded as failure | Monkeypatch `hash_file` to raise `FileChangedDuringHashingError` → failure recorded, others continue |
| Permission error during preparation is recorded as failure | Monkeypatch `hash_file` to raise `PermissionError` → failure recorded |
| Chroma write failure for one file is recorded | FakeIndexStore raises on upsert for specific file → failure recorded, others written |
| Partial failure raises IndexPartialFailureError | Any failures → exception with JSON payload containing correct counts and sorted failure list |
| Failures are sorted by relative_path | Submit files in various orders, verify failures list is sorted |
| Workers do not access IndexStore | Verify FakeIndexStore is only called from upsert_chunks (not from worker functions) |
| All eligible files are processed even when early files fail | First N files fail → remaining files still indexed |

### `test_index_store.py` — `IndexCorruptedError`

| Test | What it verifies |
|---|---|
| `open_existing` raises `IndexCorruptedError` when DB exists but collection missing | Create PersistentClient (no collection), then `open_existing` → `IndexCorruptedError` with `NotFoundError` cause |
| `open_existing` still raises `IndexNotInitializedError` when no DB exists | Unchanged behavior for the no-DB case |
| `IndexCorruptedError` is exported | In `__all__` |

Update existing test `test_open_existing_wraps_chroma_missing_collection_error`: change expected exception from `IndexNotInitializedError` to `IndexCorruptedError`.

### `test_server.py` — `index_repo` tool wiring

| Test | What it verifies |
|---|---|
| New index: delegates to `index_repository` and returns result | Mock `open_existing` → `IndexNotInitializedError`, mock `IndexStore()` and `index_repository` → returns `initialized` result with `created=true` |
| Healthy existing index: returns `initialized` with `created=false` | Mock `open_existing` → returns store → `initialized` result with `created=false`, no walk-count fields |
| Corrupted index: raises ToolError | Mock `open_existing` → raises `IndexCorruptedError` → ToolError |
| Invalid repo_path: raises ToolError | Empty, None, missing path → ToolError |
| Partial failure: raises ToolError with JSON body | Mock `index_repository` → raises `IndexPartialFailureError` → ToolError |
| `force` parameter is removed | `inspect.signature(server.index_repo)` has only `repo_path` |
| `reindex_file` catches `IndexCorruptedError` | Mock `open_existing` → `IndexCorruptedError` → ToolError |
| FastMCP integration: index_repo creates index for a minimal repo | End-to-end via `mcp.call_tool("index_repo", ...)` with real Chroma + tmp_path |

### `test_results.py` — New result types

| Test | What it verifies |
|---|---|
| `initialized_result` with `created=True` returns walk counts | Status is `"initialized"`, `created` is `True`, `files_indexed`/`chunks_indexed`/`files_skipped` present with correct values |
| `initialized_result` with `created=False` omits walk counts | Status is `"initialized"`, `created` is `False`, walk-count keys absent from dict |
| `partial_failure_result` returns correct TypedDict | Includes `failures` list with correct structure |

## 10. Open Questions

### Q1: `iter_indexable_files` placement

The plan puts `iter_indexable_files` in `file_finder.py` alongside `should_index_file`, matching the layout in AGENTS.md. Alternative: put it in `indexer.py` since it's only used by `index_repository`. **Recommendation: `file_finder.py`** — it's a file-discovery concern, independently testable, and AGENTS.md already designates `file_finder.py` for "file filtering and repository walking."

### Q2: Worker count and batch size — Resolved

`DEFAULT_INDEX_WORKERS = 7` and `DEFAULT_INDEX_BATCH_SIZE = 32` are defined in `config.py` as centralized configuration. Workers default to 7. A batch size of 32 bounds memory while remaining large enough to amortize executor overhead. Neither worker count nor batch size is exposed as a public MCP parameter in v0.

### Q3: Chroma upsert batch size

Each file's chunks are upserted in a single `store.upsert_chunks(chunks)` call. A large file (300 KiB, 80-line chunks) could produce ~50 chunks per call. Should we sub-batch the upsert call itself? **Recommendation: No.** Chroma handles batch sizes internally, and 50 documents per upsert is well within reasonable limits. Revisit only if Chroma upserts start failing for large batches.

### Q4: `_prepare_file` exception granularity

The plan catches all exceptions from `Future.result()` uniformly. Should we distinguish `FileNotFoundError` (file disappeared, retryable via `reindex_file`) from `PermissionError` (likely persistent)? **Recommendation: No distinction needed in v0.** The failure `reason` string already includes the exception message, which is enough for an LLM to judge retryability. The `PartialFailureDetail` TypedDict could add a `retryable: bool` field later if needed.

### Q5: Progress logging

Should `index_repository` log progress (e.g., "Indexed 100/500 files")? **Recommendation: No in v0.** MCP tools return a single result; there's no streaming progress mechanism. Logging to stderr could be considered but adds complexity without clear consumer benefit.

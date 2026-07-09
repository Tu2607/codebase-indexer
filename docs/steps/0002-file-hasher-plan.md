# Spec: 0002 — SHA-256 File Hashing Helper

## Problem Statement

The indexer needs a single, well-tested way to compute the SHA-256 digest of a file's raw bytes. Later steps (file finder, chunker, index store, `search_repo_context` staleness detection, chunk IDs, `get_index_status` currentness reporting) all depend on this primitive. Adding it as its own small step keeps the module boring, isolated, and easy to test before it gets consumers.

## Scope

### In Scope
- New pure module `src/codebase_indexer/hashing.py` containing a SHA-256 file hashing helper.
- New `tests/` directory (first tests in the repo) with focused unit tests for the hashing helper in `tests/test_hashing.py`.
- New step record `docs/steps/0002-sha256-file-hashing.md` following the established convention.

### Out of Scope
- Any change to `config.py` or `server.py`.
- `file_finder.py`, `chunker.py`, `index_store.py`.
- Wiring hashing into any MCP tool (`index_repo`, `reindex_file`, `search_repo_context`, `get_index_status`).
- Chunk ID construction, stale-result detection, or ChromaDB access.
- Adding a runnable server entrypoint.
- Any change to `Pipfile` / `Pipfile.lock` beyond adding `pytest` as a dev dependency so the tests can run.
- Locking (`fcntl.flock`, `msvcrt.locking`, advisory or mandatory), temp-file copy-then-hash strategies, file watchers, and platform-specific atomic read paths — see Requirements §3 for the deferral rationale.

## Requirements

1. Provide a single public function named `hash_file` that computes the SHA-256 hex digest of a file's bytes.
   - Accepts a filesystem path typed as `str | os.PathLike[str]` and normalizes it internally via `pathlib.Path`.
   - Returns a lowercase hex digest `str` (64 chars). No tuple, no size, no metadata — digest only.
   - Reads the file in binary mode and hashes the raw bytes (no normalization, no text decoding), matching AGENTS.md.
   - Streams the file in fixed-size chunks of **64 KiB** so files larger than one buffer hash correctly and memory use stays bounded. The buffer size is a module-private constant; it is **not** a public parameter in v0.

2. Pre-hash existence and regular-file check:
   - Before opening the file, explicitly verify with `Path.is_file()` that the path exists and refers to a regular file.
   - If the path does not exist → raise `FileNotFoundError`.
   - If the path exists but is not a regular file (directory, device, socket, FIFO, broken symlink) → raise `IsADirectoryError` for directories, otherwise a plain `OSError` with a short message identifying the offending path.
   - **TOCTOU acknowledgement:** this check races with any other process that can mutate the filesystem. The file may be deleted, replaced, or truncated between the check and the subsequent `open()`. When that happens, the underlying `OSError` from `open()` (typically `FileNotFoundError`) propagates unchanged; we do not attempt to paper over it. The check exists to give a clear early failure in the common single-actor case, not to close the race.

3. In-flight edit safety — stat-before / stat-after consistency guard (v0 approach, no locking):
   - **Concern:** another agent, editor, or process may be writing to an indexed file while `hash_file` is running. Streaming a hash across such a write can yield a digest that represents a mix of "before" and "after" bytes and corresponds to no real on-disk state. Silently returning that digest is worse than failing, because it flows into chunk IDs and staleness comparisons and looks legitimate.
   - **Guard:** capture `Path.stat()` immediately before opening the file, and capture `Path.stat()` again on the same path immediately after the streaming read completes. Compare `st_size` and `st_mtime_ns` only — no fallback to second-granularity `st_mtime`, and `st_ino` / `st_dev` are intentionally excluded. If either differs, treat the read as inconsistent. The guard is always on in v0; there is no `strict=` / `check_consistency=` opt-out parameter.
   - **On inconsistency:** raise a distinctly-typed, retryable error `FileChangedDuringHashingError(OSError)` defined in `hashing.py`. Do **not** return the digest. The exception message should include the path and which field changed. `hash_file` itself **must not** retry internally — it raises exactly once. Callers (later steps: `index_repo`, `reindex_file`) decide whether to retry, defer, or bubble; hiding the concurrency signal inside a bounded internal retry loop is explicitly rejected.
   - **Explicit non-goals for v0** (each is deferred, not adopted):
     - No advisory or mandatory file locking (`fcntl.flock`, Windows `LockFileEx`).
     - No copy-to-temp-then-hash strategy.
     - No file watchers / inotify / FSEvents / `ReadDirectoryChangesW`.
     - No platform-specific atomic read paths (macOS `O_EXLOCK`, filesystem snapshots, etc.).
   - **Rationale:** the stat guard adds two cheap syscalls per hash, catches the common "editor rewrote the file mid-index" case, and fails loudly instead of returning garbage. Anything stronger requires OS-specific work or a copy step, neither of which fits v0's "boring and readable" bar. This can be revisited when a concrete false-negative or false-positive is observed in practice.
   - **Known residual gaps** (accepted for v0): a writer that finishes within the same nanosecond mtime tick and preserves size will not be detected; a rename-in-place that swaps inodes but preserves size and mtime will not be detected (inode/device are intentionally not part of the comparison to keep the check simple). These are documented, not fixed.

4. Error behaviour stays boring and predictable:
   - Missing file → `FileNotFoundError`.
   - Non-regular path (directory, socket, etc.) → `IsADirectoryError` or plain `OSError` as above.
   - Unreadable file (permission, IO error) → underlying `OSError` propagates.
   - File changed during hashing (size or mtime mismatch across the read) → `FileChangedDuringHashingError` (subclass of `OSError`).

5. Pure module: no imports from `config`, `server`, or any not-yet-existing sibling module. No global state beyond module-level constants and the `FileChangedDuringHashingError` class. `hash_file` is stateless: it does not maintain a hashmap, cache, in-memory registry, or any pending-reindex tracking. Any "this file needs a re-hash later" bookkeeping belongs to a separate orchestration / index-state layer built in a later step (see Follow-ups).

6. Empty file must hash to the standard SHA-256 of the empty byte string (`e3b0c442...b855`).

7. Public surface is exactly `hash_file` and `FileChangedDuringHashingError`. `hashing.py` must declare `__all__ = ["hash_file", "FileChangedDuringHashingError"]` at module top level so `from codebase_indexer.hashing import *` and static analysis tools see the same surface. No class beyond that error type, no context manager, no helper for hash prefixes yet (chunk-ID prefix logic can slice the digest string when that step lands).

## Acceptance Criteria

- [ ] `src/codebase_indexer/hashing.py` exists, exports exactly `hash_file` and `FileChangedDuringHashingError`, and declares `__all__ = ["hash_file", "FileChangedDuringHashingError"]` at module top level.
- [ ] `tests/test_hashing.py` exists at a **flat** `tests/` layout (no `tests/unit/` subtree, no `conftest.py` in this step) and covers, at minimum:
  - [ ] Known-input digest equals a hard-coded expected hex string (e.g. SHA-256 of `b"hello world"`).
  - [ ] Empty file hashes to the empty-string SHA-256 digest.
  - [ ] Two files with identical byte content produce identical digests.
  - [ ] Modifying a file's bytes changes the digest.
  - [ ] A file larger than the 64 KiB internal read buffer still produces the same digest as hashing its bytes in one shot.
  - [ ] Missing file path raises `FileNotFoundError` (via the pre-hash existence check).
  - [ ] Path pointing at a directory raises `IsADirectoryError` (or `OSError`) *without* attempting to open it for read.
  - [ ] The function accepts both `str` and `os.PathLike` (`pathlib.Path`) inputs and returns the same digest for the same file.
  - [ ] In-flight edit — size change: when `st_size` differs between the pre-read and post-read `stat()` calls, `hash_file` raises `FileChangedDuringHashingError` and does not return a digest.
  - [ ] In-flight edit — mtime change: when `st_mtime_ns` differs between the pre-read and post-read `stat()` calls (but size does not), `hash_file` raises `FileChangedDuringHashingError`.
  - [ ] Stable read (no concurrent modification) produces no false positive: repeated calls on an untouched file return the same digest with no exception.
  - [ ] `FileChangedDuringHashingError` is a subclass of `OSError` so callers can catch it either specifically or via broad `OSError` handling.
  - [ ] `hash_file` does not retry internally on `FileChangedDuringHashingError`: with `Path.stat` patched so the second call differs from the first, exactly one exception reaches the caller (asserted via a call-count check on the patched `stat`, confirming no hidden retry loop re-opens the file).
- [ ] `docs/steps/0002-sha256-file-hashing.md` exists with sections mirroring 0001: Goal, Changes, Decisions, Rationale, Tests, Follow-ups. Decisions section explicitly records: (a) the stat-consistency guard with fields fixed at `st_size` + `st_mtime_ns` only, (b) the deferral of locking / copy-then-hash / watchers / platform-specific atomic reads, (c) the "raise once, no internal retry" policy for `FileChangedDuringHashingError`, (d) that the guard is always on with no opt-out parameter, and (e) that `hash_file` stays pure/stateless — pending-reindex tracking is a separate orchestration concern. Follow-ups section records the pending-reindex flag design note (in-memory `dict`/`set` for v0, persistent metadata under `.codebase-index/` later; cleared on successful `reindex_file` or `delete_file_from_index`).
- [ ] Existing files (`config.py`, `server.py`, `__init__.py`, `docs/steps/0001-*.md`, `docs/steps/README.md`) are unchanged.
- [ ] `pytest` is present in `Pipfile` `[dev-packages]` and the test suite runs green under Pipenv (`pipenv run pytest`).

## Task Order

1. Add `src/codebase_indexer/hashing.py` with the SHA-256 helper.
2. Add `tests/` directory and `tests/test_hashing.py` covering the cases in Acceptance Criteria.
3. If needed, add `pytest` as a Pipfile dev dependency (see Open Questions) so the tests can run.
4. Run the test suite and confirm all tests pass.
5. Write `docs/steps/0002-sha256-file-hashing.md` documenting the step, decisions, tests, and follow-ups (e.g. wiring hashing into `file_finder` / `index_store` and using the digest prefix in chunk IDs).

## Test Strategy

- Framework: `pytest`, invoked via `pipenv run pytest` (Pipenv is the existing dependency manager per step 0001). `pytest` is added to `[dev-packages]` in `Pipfile` as part of this step.
- Location: `tests/test_hashing.py`, using `tmp_path` for file fixtures — no network, no external services.
- All positive-path assertions are deterministic (fixed input bytes → fixed digests).
- Large-file case uses a synthetic buffer a few times larger than the 64 KiB internal read buffer; it does not need to approach the 300 KB skip threshold.
- Directory-input case creates a `tmp_path` subdirectory and passes it to `hash_file`, asserting the expected exception type without any file being opened for read.
- In-flight edit cases are simulated deterministically — do **not** rely on real sleeps or filesystem mtime granularity:
  - Use `monkeypatch` to wrap `pathlib.Path.stat` (or the module-level `stat` binding) so the second call returns a `stat_result` with a different `st_size` or `st_mtime_ns` than the first. This lets the test assert the guard fires without needing a second process.
  - As a lighter-weight alternative for at least one case, mutate the file's mtime with `os.utime(..., ns=(atime_ns, mtime_ns))` after the file handle is opened but before the stream is fully consumed (e.g. via a small wrapper around the read loop exposed for testing, or by patching `hashlib.sha256().update` to bump mtime on first call).
  - Assert both the exception type (`FileChangedDuringHashingError`) and that it is an `OSError` subclass.
- No-internal-retry case: patch `Path.stat` so the pre-read and post-read calls disagree, then assert that `hash_file` raises `FileChangedDuringHashingError` on the first attempt and that the patched `stat` was called exactly the expected number of times (i.e. no hidden retry loop re-reads the file).
- Stable-read case asserts no false positive: a file created, closed, and left untouched hashes cleanly across repeated `hash_file` calls.

## Open Questions

None remaining. All prior open questions are resolved and their decisions are already reflected in Requirements, Acceptance Criteria, and Test Strategy above. Recorded here for traceability only:

- Pytest may be added to `Pipfile` `[dev-packages]` as part of this step.
- Public function name is `hash_file`.
- Input type is `str | os.PathLike[str]`, normalized internally via `pathlib.Path`.
- Return shape is the hex digest `str` only.
- Read buffer size is 64 KiB, module-private, not a parameter.
- Retryable-error class name is **`FileChangedDuringHashingError`** (spelled "Hashing", not "Hash"), subclass of `OSError`, defined in `hashing.py`.
- Consistency fields are `st_size` and `st_mtime_ns` **only** for v0. `st_ino` / `st_dev` are intentionally excluded (atomic-writer editors legitimately rotate inodes) and there is no fallback to second-granularity `st_mtime`.
- Retry policy: `hash_file` never retries internally on `FileChangedDuringHashingError`. It raises exactly once and the caller decides whether to retry, defer, or surface the failure.
- Guard is always on. No `strict=` / `check_consistency=` opt-out parameter in v0.
- `hashing.py` declares `__all__ = ["hash_file", "FileChangedDuringHashingError"]`.
- Test layout is a flat `tests/` directory with `tests/test_hashing.py` and no `conftest.py` yet.

## Follow-ups

Explicitly out of scope for step 0002; recorded here so they are not lost when a later step picks them up.

1. **Pending-reindex flag / orchestration layer.** When `hash_file` raises `FileChangedDuringHashingError`, some caller — a later orchestration step layered above `index_repo` / `reindex_file` — should mark the affected path as "needs re-hash on next opportunity". This bookkeeping does **not** belong in `hashing.py`; `hash_file` stays pure and stateless. Design sketch to finalize in a later step:
   - **v0 storage:** an in-memory `dict[str, ...]` or `set[str]` keyed by the file's normalized path, held by the index-state module (likely `index_store.py` or a small new state helper). Cheap, no on-disk format churn, lost on restart (acceptable for v0).
   - **v0+ storage:** persistent metadata under `.codebase-index/` (small JSON sidecar or Chroma metadata entry) so pending-reindex state survives server restarts.
   - **Lifecycle:** the flag is *set* when `hash_file` raises `FileChangedDuringHashingError` for a path during `index_repo` or `reindex_file`. It is *cleared* on the next successful `reindex_file(path)` or `delete_file_from_index(path)`. `get_index_status` should surface the current set so agents can see which paths are known-stale.
   - **Not decided yet:** retry cadence, whether to expose an explicit `retry_pending_reindexes` MCP tool, and whether persistence lands as JSON, sqlite, or Chroma metadata. Track in a dedicated follow-up step.
2. Wiring `hash_file` into `file_finder` (skip unchanged files during walk) and `index_store` (staleness comparison in `search_repo_context`, chunk-ID prefix construction from the digest).
3. Revisiting the stat-consistency guard if a concrete false-positive or false-negative is observed in practice — potential upgrades include copy-to-temp-then-hash, advisory locking (`fcntl.flock` / `LockFileEx`), or platform-specific atomic read paths.
4. Known residual gaps accepted for v0 (documented in Requirements §3): a writer that completes within the same nanosecond mtime tick and preserves size will not be detected; a rename-in-place that swaps inodes but preserves size and mtime will not be detected. Revisit only if observed in practice.

# 0002 SHA-256 File Hashing

Date: 2026-07-09
Status: implemented

## Goal

Add a focused SHA-256 file hashing helper so later indexing work can detect
file changes without wiring ChromaDB, file discovery, chunking, or MCP tools yet.

## Changes

- Added `src/codebase_indexer/hashing.py`.
- Added `hash_file(path)` to hash raw file bytes and return a lowercase
  SHA-256 hex digest.
- Added `FileChangedDuringHashingError` for retryable in-flight edit detection.
- Added flat unit tests in `tests/test_hashing.py`.
- Added `pytest.ini` so `pipenv run pytest` can import the `src/` package.
- Added `pytest` as a Pipfile dev dependency.

## Decisions

- Hash file bytes directly with SHA-256; do not decode, normalize, or transform
  content.
- Accept `str | os.PathLike[str]` and normalize internally with `pathlib.Path`.
- Return only the digest string. File size, metadata, and hash prefixes belong
  to later indexing steps.
- Use a private 64 KiB read buffer.
- Check that the path exists and is a regular file before opening it.
- Keep the consistency guard always on. `hash_file` records `st_size` and
  `st_mtime_ns` before and after reading; if either changes, it raises
  `FileChangedDuringHashingError`.
- Defer locking, copy-then-hash, file watchers, and platform-specific atomic
  reads. Those are heavier than v0 needs.
- Do not retry inside `hash_file`. It raises once and leaves retry, defer, or
  surface decisions to future callers.
- Keep `hash_file` pure and stateless. Pending-reindex tracking is a separate
  orchestration concern, not a responsibility of the hasher.

## Rationale

Hashing is a primitive used by indexing, staleness detection, chunk IDs, and
status reporting. Keeping it isolated makes the behavior easy to test before it
is used by higher-level modules. The stat consistency guard catches common
mid-edit writes cheaply and prevents returning a digest for bytes that may not
represent one stable on-disk state.

## Tests

- Known content hashes to the expected SHA-256 digest.
- Empty files hash to the standard empty SHA-256 digest.
- Identical byte content produces identical digests.
- Modified bytes change the digest.
- Files larger than 64 KiB hash correctly.
- Missing paths raise `FileNotFoundError`.
- Directory paths raise before being opened for read.
- Broken symlinks raise `OSError`, while symlinks to regular files hash the
  target bytes.
- Both string and `Path` inputs are accepted.
- Size and mtime changes across the read raise
  `FileChangedDuringHashingError` with the path and changed field in the
  message.
- Stable repeated reads do not raise false positives.
- `FileChangedDuringHashingError` is an `OSError` subclass.
- The module public surface is explicit through `__all__`.
- `pipenv run pytest` discovers the package through `pytest.ini`.

## Follow-ups

- Add a pending-reindex state layer above hashing. A v0 shape could be an
  in-memory `set[str]` or `dict[str, ...]` keyed by normalized path, set when
  `index_repo` or `reindex_file` catches `FileChangedDuringHashingError`.
- Clear pending-reindex state after a successful `reindex_file(path)` or
  `delete_file_from_index(path)`.
- Surface pending-reindex paths through `get_index_status`.
- Decide later whether pending-reindex state should persist under
  `.codebase-index`.
- Wire `hash_file` into file discovery, index storage, stale-result checks, and
  chunk ID construction.

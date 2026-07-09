# 0003 Line-Based Chunking

Date: 2026-07-09
Status: implemented

## Goal

Split repository files into stable, overlapping line-based chunks for future
embedding storage without adding indexing, ChromaDB, or MCP orchestration.

## Changes

- Added `src/codebase_indexer/repo_id.py` with `repo_path_hash(path)`.
- Added `src/codebase_indexer/chunker.py` with the frozen `TextChunk` value
  type and `chunk_by_lines(...)`.
- Added focused tests in `tests/test_repo_id.py` and `tests/test_chunker.py`.

## Decisions

- Repository identity is a reusable 12-character SHA-256 prefix derived from
  the resolved absolute repository path. It lives in `repo_id.py`, separate
  from `hashing.py`, which hashes file content.
- The chunker accepts a caller-provided file hash. It does not hash files or
  provide a hash/read consistency guarantee; later reindex orchestration owns
  that transaction boundary.
- Normalize `repo_path` and `file_path` to resolved absolute paths. Store them
  in metadata alongside a POSIX repository-relative path. Reject paths outside
  the repository with `ValueError` before opening the file.
- Read UTF-8 text with replacement for invalid bytes and `newline=""`, then
  use `splitlines(keepends=True)` to preserve original line endings.
- Use 1-based inclusive line ranges. Default chunks contain 80 lines with a
  10-line overlap; callers may override either setting when the overlap is
  non-negative and smaller than the chunk size.
- Emit a trailing chunk only when it contributes at least one line beyond the
  preceding chunk. This avoids overlap-only chunks for files exactly matching a
  chunk boundary.
- Chunk IDs use `{repo_hash}:{relative_path}:{chunk_index}:{file_hash_prefix}`.
  The index is 0-based, and the file hash prefix is 12 characters.
- Let `FileNotFoundError` propagate unchanged from the file read.

## Rationale

Fixed line windows can split a function or other logical block. The overlap
retains nearby boundary context but cannot retain a complete long function.
That tradeoff is appropriate for v0 because search results are pointers to a
file and line range, not complete edit context; agents must read the current
source file before editing.

## Tests

- Repository path hash determinism, normalization, format, and accepted path
  input types.
- Single-chunk, exact-boundary, and overlapping multi-chunk behavior.
- Zero-overlap chunks and symlinks that resolve outside the repository.
- Line ranges, metadata, deterministic IDs, file-hash prefixes, and path input
  types.
- Empty files, missing files, out-of-repository paths, invalid chunk settings,
  invalid UTF-8 bytes, files without trailing newlines, and mixed line endings.
- `pipenv run pytest` passes: 39 tests.

## Follow-ups

- Use `repo_path_hash` in index storage and status operations that need a
  repository identifier.
- Consider adjacent-chunk retrieval when a future search layer needs broader
  local context around a match.
- Consider syntax-aware or function-aware chunking only if fixed line windows
  prove insufficient for v0 retrieval quality.

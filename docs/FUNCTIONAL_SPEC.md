# Functional specification

This document is the detailed behavioral reference for
`codebase-indexer-mcp`. Start with [`../AGENTS.md`](../AGENTS.md) for repository
orientation and development commands. Read
[`ARCHITECTURE.md`](ARCHITECTURE.md) for design decisions and module boundaries.

## Implementation status

The tool surface is registered up front, but implementation is incremental.

| Tool | Status | Notes |
| --- | --- | --- |
| `index_repo` | Implemented | Creates an absent index; a healthy existing index is a no-op. |
| `reindex_file` | Implemented | Replaces records for one existing, indexable path. |
| `delete_file_from_index` | Scaffolded | Currently raises a FastMCP `ToolError`. |
| `search_repo_context` | Scaffolded | Currently raises a FastMCP `ToolError`. |
| `get_index_status` | Scaffolded | Currently raises a FastMCP `ToolError`. |
| `rebuild_index` | Reserved | Not registered or implemented in v0. |

[`steps/`](steps/) records completed work and upcoming implementation slices.
Update this table when a scaffold becomes usable.

## Cross-tool invariants

Every index-backed operation follows these rules:

- `repo_path` is explicit; the server never guesses the repository root.
- Repository and file paths are resolved to canonical paths before storage
  access.
- A file path must remain inside the resolved repository, including after
  symlink resolution.
- Stored file paths are repository-relative so one file can be selected and
  replaced deterministically.
- Tool results are plain dictionaries and lists with stable discriminator
  fields, not dataclasses or custom serialization objects.
- Expected validation and index-state failures become FastMCP `ToolError`s.
  Unexpected programming or infrastructure errors are allowed to propagate.
- Search and status operations must not mutate indexed content.

## Index lifecycle

An index has three meaningful states:

1. **Absent:** `.codebase-index` does not contain a usable database. Calling
   `index_repo` creates it and performs the initial repository walk.
2. **Healthy:** the database and configured collection can be opened. Calling
   `index_repo` returns immediately without walking, hashing, or writing.
3. **Corrupted or inconsistent:** database files exist but cannot be opened, or
   the expected collection is missing. Tools report recovery guidance rather
   than treating this as a new index.

Initialization is intentionally different from synchronization. A healthy
index can still contain stale files, and `index_repo` does not refresh them.
Routine updates are always path-specific.

## `index_repo`

`index_repo(repo_path: str) -> dict`

The tool validates the repository, creates its local store, discovers eligible
files in deterministic order, and prepares them in bounded batches. Preparation
includes filtering, byte-level SHA-256 hashing, and line chunking. ChromaDB
writes are serialized on the calling thread even when preparation uses worker
threads.

One file failure does not discard successful files. Preparation and write
failures are collected by relative path and reported as a partial failure so
each affected file can later be retried with `reindex_file`.

The tool returns an initialized result with `created: false`. Walk counts are
omitted because no discovery work occurred.

Successful result shape:

```json
{
  "status": "initialized",
  "repo_path": "/absolute/repository",
  "index_path": "/absolute/repository/.codebase-index",
  "created": true,
  "files_indexed": 12,
  "chunks_indexed": 31,
  "files_skipped": 8
}
```

For `created: false`, only `status`, `repo_path`, `index_path`, and `created`
are present.

Partial-failure details contain `relative_path` and `reason`, alongside the
successful file, chunk, skip, and failure counts. At the MCP boundary this is
reported as a `ToolError` carrying the structured failure information.

## `reindex_file`

`reindex_file(repo_path: str, file_path: str) -> dict`

`file_path` may be relative to the repository or an absolute path inside it.
The tool requires an existing healthy index and has four outcomes. Missing and
unindexable targets are reported without changing stored chunks:

| Status | Condition | Effect |
| --- | --- | --- |
| `reindexed` | File exists and is eligible | Upserts current chunks, then removes obsolete chunk IDs. |
| `file_not_found` | File no longer exists | Reports the missing path without mutation. |
| `not_indexable` | File exists but does not pass selection | Reports the reason without mutation. |
| `hash_failed` | File changes while being hashed | Leaves old chunks intact and returns `retryable: true`. |

Normal successful shape:

```json
{
  "status": "reindexed",
  "relative_path": "src/example.py",
  "file_hash": "<sha256>",
  "chunks_added": 2,
  "chunks_removed": 1
}
```

Upserting new chunks before removing obsolete IDs preserves the old index when
embedding or upsert fails. Reindexing unchanged content is idempotent because
chunk IDs are deterministic.

Removing obsolete chunk IDs during a successful replacement is distinct from
file-level deletion. Call `delete_file_from_index` explicitly for deleted
paths, old rename paths, and indexed files that are no longer eligible.

An empty eligible file is still a successfully reindexed file: it produces no
new chunks and removes any old chunks.

## Planned deletion behavior

`delete_file_from_index(repo_path: str, file_path: str) -> dict`

This tool will remove every chunk associated with a repository-relative path,
whether or not the file still exists. It is the explicit cleanup operation for
deletions and the old side of a rename.

For a rename, delete the old path and then reindex the new path.

## Planned search behavior

`search_repo_context(repo_path: str, query: str, max_results: int = 5,
include_stale: bool = False) -> list[dict]`

Each match should include:

- Absolute and repository-relative file paths.
- One-based start and end line numbers.
- Chunk content.
- Vector distance or a clearly defined score.
- The indexed file hash and a stale indicator.

For each candidate, search compares the stored hash with the current file's
byte-level SHA-256 hash. Missing or changed files are stale. Search must never
repair, reindex, or delete content as a side effect.

When `include_stale` is false, stale matches should be omitted. When it is true,
they may be returned but must be unmistakably marked. Results remain discovery
hints; callers read the file itself before editing.

## Planned status behavior

`get_index_status(repo_path: str | None = None) -> dict`

Status output is intended for diagnosis and should include the resolved index
path, collection name, indexed file count, chunk count, and a small sample of
indexed paths. Stale-file reporting may be included if it can be computed
without hidden updates.

If `repo_path` remains optional, its no-argument semantics must be defined
explicitly before implementation; other index-backed tools do not infer a
repository.

## File-change edge cases

Filesystem state can change between filtering, hashing, chunking, and writing.
Implementations should preserve these properties:

- A disappearance at any pre-write stage is reported as `file_not_found` and
  preserves existing indexed content.
- An existing file that does not pass indexing selection is reported as
  `not_indexable` and preserves existing indexed content.
- A concurrent write detected during hashing returns a retryable outcome and
  preserves existing chunks.
- Read and permission errors are reported without silently deleting known-good
  indexed content.
- A failed ChromaDB upsert preserves old chunks.
- A failure while removing obsolete IDs is surfaced; it must not be reported
  as a clean success.
- Symlinks that resolve outside the repository are rejected before store
  mutation.

## Recovery policy

No current tool performs destructive recovery. If an index is corrupted, the
error should direct the caller to the future `rebuild_index` workflow. Until
that workflow exists, recovery is a deliberate manual action; neither
`index_repo` nor `reindex_file` should erase the index automatically.

## Completion target

Version 0 is functionally complete when the server starts, initial indexing
works on a local repository, search returns useful chunks with paths and line
ranges, single-file reindexing replaces changed content, and search detects
stale records. The final user documentation must also explain how to run and
configure the MCP server once a runnable entry point is added.

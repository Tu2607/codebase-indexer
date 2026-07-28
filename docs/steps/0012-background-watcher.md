# Step 0012: Background Watcher

Status: implemented on 2026-07-21.

## Outcome

The agent can skip an unnecessary full `get_index_status` repository walk on
read-only turns when nothing has changed. An explicitly started background
watcher flips an in-memory dirty bit on qualifying filesystem events, and a
cheap status tool exposes that bit.

`get_index_status` remains authoritative and owns the dirty-bit lifecycle.
Editing tasks still run full reconciliation before editing and verify it again
after editing.

## Non-goals

- No automatic reindexing or deletion; the agent still invokes existing tools.
- No relaxation of pre-edit or post-edit clean-index checks.
- No cross-session persistence, changed-path queue, subprocess, pidfile, or IPC.
- No public `stop_watcher` tool.
- No multiple watched repositories in one MCP server process.

## Implemented architecture

- `dirty_flag.py` — thread-safe `DirtyFlag` and module singleton `DIRTY`.
- `watcher.py` — `watchfiles` worker thread, event classification, lifecycle
  lock, watched path, state inspection, and internal test/shutdown cleanup.
- `path_utils.py` — event-path normalization, repository-boundary checks, and
  skipped-directory filtering shared with the watcher.
- `file_finder.py` — path-only eligibility predicate backed by the existing
  constants in `config.py`.
- `server.py` — watcher start, status, and dirty-setter tools plus dirty-state
  handling in `get_index_status`.
- `results.py` — watcher and expanded index-status result contracts.

MCP definitions stay in `server.py`; testable logic stays in helper modules.

## Contracts

### Dirty flag

```python
class DirtyFlag:
    def set(self, value: bool = True) -> None: ...
    def is_set(self) -> bool: ...
    def check_and_clear(self) -> bool: ...
```

Use `threading.Lock`. `check_and_clear` atomically clears the previous signal
before a full scan, allowing an event during that scan to set a new signal.
`is_set` is a non-mutating peek.

### Path-only eligibility

The shared helper is:

```python
def is_index_candidate_path(file_path: Path, repo_path: Path) -> bool: ...
```

It performs lexical checks only:

- the path is inside the resolved repository;
- no parent component appears in `SKIP_DIRECTORIES`;
- its suffix is in `INDEX_EXTENSIONS`, or its name is in `INDEX_FILENAMES`.

It does not call `stat`, require existence, check regular-file status, or apply
the size limit. `should_index_file` first applies the same path rules and then
retains those filesystem-dependent checks.

This shares `config.py` policy between normal discovery and the watcher while
supporting deletes, move sources, and indexed files that become oversized.
False-positive dirty signals are acceptable; false negatives are not.

### Watcher event handling

Run synchronous `watchfiles.watch` in a daemon Python thread at the resolved
repository root with `recursive=True` and an internal `threading.Event` passed
as `stop_event`. Process each yielded batch as one dirty signal:

- A custom `watch_filter` rejects paths under configured skipped directories,
  especially `.git/` and `.codebase-index/`.
- Added and modified paths set `DIRTY` when they are candidate files or
  directories outside skipped trees.
- Deleted paths outside skipped trees set `DIRTY` conservatively because the
  vanished path cannot reliably be distinguished from a deleted directory.
- Renames are handled through the added/deleted paths emitted by the backend.

`watchfiles` may group rapid changes into one yielded set; the dirty-bit model
needs no additional debounce or per-path queue.

### Watcher lifecycle

`watcher.start(repo_path: Path) -> WatcherState`:

- receives an already validated, resolved repository path;
- returns `already_running` for a live worker on the same path;
- rejects a different path while a live worker exists;
- replaces dead worker state before restarting;
- confirms the worker thread is alive before returning success;
- calls `DIRTY.set()` after first start or restart to require a baseline scan;
- leaves no partial state when startup fails.

Return:

```python
{
    "status": "started" | "already_running",
    "repo_path": str,
    "watcher_running": True,
    "dirty": bool,
}
```

Store the worker thread, `threading.Event` stop signal, watched path, last worker
error, and lifecycle `Lock` at module scope. Concurrent starts must not create
duplicates. Worker exceptions set `DIRTY`, make `watcher_running` false, and
remain available for diagnostics. Provide an internal stop-and-join helper for
deterministic cleanup, but no MCP stop tool.

### `start_watcher`

```python
start_watcher(repo_path: str) -> WatcherState
```

Validate with `validate_repo_path`. Translate expected validation and immediate
thread-start failures to `ToolError`. Later worker failures are exposed through
`watcher_running=false`; agents then fall back to full scans.

### `get_watcher_status`

```python
get_watcher_status(repo_path: str) -> WatcherStatus
```

Return without index access or a repository walk:

```python
{
    "repo_path": str,
    "watcher_running": bool,
    "dirty": bool,
}
```

Validate the path. Reject a request for a different repository while another
live watcher exists. A missing or dead worker reports `watcher_running=false`;
`dirty=false` must not skip a scan in that state. This tool never clears
`DIRTY`.

### `set_index_dirty`

```python
set_index_dirty(repo_path: str, dirty: bool) -> WatcherStatus
```

Validate watcher ownership, set the process-local flag, and return cheap
watcher status without index access or a repository walk. Setting false is
reserved for a known edit batch whose per-file reindex and deletion calls all
succeeded and is rejected without a running watcher. The returned value is
authoritative because a concurrent event may immediately keep dirty true;
uncertainty and important structural changes use full status.

### `get_index_status`

The existing response gains `watcher_running` and `dirty`. Existing fields and
action contracts remain unchanged. Each full call:

1. Calls `DIRTY.check_and_clear()` immediately before scanning.
2. Runs the existing repository/index comparison.
3. Calls `DIRTY.set()` if any reindex action, deletion action, or error exists.
4. Returns `dirty=DIRTY.is_set()`, preserving events received during the scan.
5. Calls `DIRTY.set()` before propagating a scan exception.

Central invariant:

> `dirty=false` is actionable only when `watcher_running=true`. It means the
> latest complete status scan found no actions or errors and no later
> qualifying event has been observed.

Errors stay dirty because an incomplete comparison did not prove cleanliness.

### Per-file tools

`reindex_file` and `delete_file_from_index` never clear the repository-wide
flag. The caller uses `set_index_dirty(false)` after completely reconciling a
known edit batch, or full status for unknown and important changes. Deletes and
renames continue through the existing explicit actions.

## Lifecycle and agent workflow

1. MCP server starts with no worker and `DIRTY=False`.
2. Agent calls `index_repo(repo_path)` and `start_watcher(repo_path)`.
3. Watcher startup marks dirty; agent runs the full status/reconciliation loop
   to establish a clean baseline.
4. A qualifying event sets `DIRTY`.
5. On a read-only turn, clean state uses normal search; dirty state may use
   stale search for navigation and direct source inspection.
6. A known edit batch performs explicit per-file index updates and then sets
   dirty false. Unknown state, failures, and important structural edits use
   full authoritative reconciliation.
7. On shutdown, stop and join when lifecycle integration permits; daemon exit
   is the fallback. A resumed process repeats startup and baseline scanning.

Update `AGENTS.md` accordingly. Replace wording that says the watcher performs
routine synchronization: it detects possible changes but never updates index
content.

## Edge cases

- Rapid events coalesce into one true bit; no debounce is needed.
- An event during a scan remains set because the prior flag was cleared first.
- Partial reconciliation and status errors keep dirty true.
- A dead worker reports not running; restart marks dirty and requires a new
  baseline.
- A different repository is rejected while the process owns a live watcher.
- Unsupported filesystem backends surface a tool error; agents use full scans.
- Event paths outside the resolved root are never eligible.
- Move source/destination handling covers common editor atomic-save behavior.

## Validation

- `test_dirty_flag.py`: set, peek, atomic clear, and concurrent synchronization.
- `test_file_finder.py`: config-backed lexical selection; nonexistent paths;
  retained regular-file and size checks in `should_index_file`.
- `test_watcher.py`:
  - first start, idempotency, path mismatch, dead restart, and startup failure;
  - file create/modify/delete, both move paths, and relevant directory events;
  - ignored trees and unsupported files;
  - thread-safe duplicate-start prevention and leak-free cleanup.
- `test_server.py`:
  - watcher tools registered with explicit arguments and expected `ToolError`s;
  - cheap status performs no index access or repository walk;
  - dirty setter updates both boolean states without index access;
  - actions and errors stay dirty; a clean scan clears dirty;
  - mid-scan events remain dirty; scan exceptions restore dirty;
  - watcher fields appear in full status results.
- `test_results.py`: stable plain-dict contracts.

The focused watcher, filtering, result, status, and server tests passed. The
full default suite passed with 346 tests and two smoke tests deselected. The
native macOS FSEvents integration also passed outside the filesystem sandbox;
the default sandboxed test forces watchfiles polling for deterministic delivery.
`pipenv verify`, `git diff --check`, and the server import check also passed.

## Documentation updated

- `AGENTS.md` documents the read-only fast path and unchanged edit guarantees.
- `docs/FUNCTIONAL_SPEC.md` defines the new tools and dirty-state contracts.
- `docs/ARCHITECTURE.md` records watcher components, filtering, and the
  process boundary.
- `README.md` lists all nine tools and the watcher-aware workflow.

## Dependency decision

`watchfiles>=1.2,<2` is declared directly in `Pipfile`. Version 1.2.0 was already
resolved in the lock and imports successfully in the project's CPython 3.14.3
macOS ARM64 environment. The direct declaration makes it an intentional runtime
contract rather than relying on the existing transitive dependency.

Use the synchronous `watchfiles.watch` API in the worker thread. No asyncio
integration or alternate package index is required.

## Follow-ups

- Public `stop_watcher` tool.
- Cross-session persistence or a detached watcher process.
- Per-path event queue.
- Multiple watched repositories per MCP process.
- More selective backend-level event suppression.
- `SessionStart` hook integration.

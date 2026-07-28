"""Single-repository background filesystem watcher lifecycle."""

from __future__ import annotations

import atexit
import threading
from pathlib import Path

from watchfiles import Change, watch

from .dirty_flag import DIRTY
from .file_finder import is_index_candidate_path
from .path_utils import is_event_path_allowed, resolve_event_path
from .results import (
    WatcherState,
    WatcherStatus,
    watcher_state_result,
    watcher_status_result,
)

__all__ = ["get_status", "is_running", "start"]

_LIFECYCLE_LOCK = threading.Lock()
_watcher_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None
_watched_path: Path | None = None
_last_worker_error: Exception | None = None


def start(repo_path: Path) -> WatcherState:
    """Start the process-wide watcher or return its existing state."""

    global _last_worker_error, _stop_event, _watched_path, _watcher_thread

    resolved_repo_path = repo_path.resolve()
    with _LIFECYCLE_LOCK:
        if _watcher_thread is not None and _watcher_thread.is_alive():
            if _watched_path != resolved_repo_path:
                raise ValueError(
                    "Watcher is already running for a different repository: "
                    f"{_watched_path}"
                )
            return watcher_state_result(
                "already_running",
                str(resolved_repo_path),
                watcher_running=True,
                dirty=DIRTY.is_set(),
            )

        DIRTY.set()
        stop_event = threading.Event()
        worker = threading.Thread(
            target=_run_watcher,
            args=(resolved_repo_path, stop_event),
            daemon=True,
            name="codebase-indexer-watcher",
        )
        _watcher_thread = worker
        _stop_event = stop_event
        _watched_path = resolved_repo_path
        _last_worker_error = None

        try:
            worker.start()
        except Exception:
            _watcher_thread = None
            _stop_event = None
            _watched_path = None
            raise

        if not worker.is_alive():
            _watcher_thread = None
            _stop_event = None
            _watched_path = None
            raise RuntimeError("Watcher worker stopped during startup.")

        return watcher_state_result(
            "started",
            str(resolved_repo_path),
            watcher_running=worker.is_alive(),
            dirty=DIRTY.is_set(),
        )


def get_status(repo_path: Path) -> WatcherStatus:
    """Return cheap watcher state without reading the repository or index."""

    resolved_repo_path = repo_path.resolve()
    with _LIFECYCLE_LOCK:
        running = _watcher_thread is not None and _watcher_thread.is_alive()
        watched_path = _watched_path

    if running and watched_path != resolved_repo_path:
        raise ValueError(
            "Watcher is running for a different repository: " f"{watched_path}"
        )
    if not running:
        raise ValueError(
            "Watcher is not running for this repository; call start_watcher."
        )

    return watcher_status_result(
        str(resolved_repo_path),
        watcher_running=True,
        dirty=DIRTY.is_set(),
    )


def is_running(repo_path: Path) -> bool:
    """Return whether a live worker owns the requested repository."""

    resolved_repo_path = repo_path.resolve()
    with _LIFECYCLE_LOCK:
        return bool(
            _watcher_thread is not None
            and _watcher_thread.is_alive()
            and _watched_path == resolved_repo_path
        )


def _run_watcher(repo_path: Path, stop_event: threading.Event) -> None:
    global _last_worker_error

    try:
        for changes in watch(
            repo_path,
            watch_filter=lambda change, path: is_event_path_allowed(path, repo_path),
            stop_event=stop_event,
            recursive=True,
            raise_interrupt=False,
        ):
            if _changes_affect_index(changes, repo_path):
                DIRTY.set()
    except Exception as exc:
        with _LIFECYCLE_LOCK:
            _last_worker_error = exc
        DIRTY.set()


def _changes_affect_index(
    changes: set[tuple[Change, str]],
    repo_path: Path,
) -> bool:
    for change, path_string in changes:
        if not is_event_path_allowed(path_string, repo_path):
            continue
        path = resolve_event_path(path_string, repo_path)

        if change is Change.deleted:
            return True
        if is_index_candidate_path(path, repo_path):
            return True
        try:
            if path.is_dir():
                return True
        except OSError:
            return True

    return False


def _stop(timeout: float = 5.0) -> None:
    """Stop the worker for deterministic tests and process cleanup."""

    global _last_worker_error, _stop_event, _watched_path, _watcher_thread

    with _LIFECYCLE_LOCK:
        worker = _watcher_thread
        stop_event = _stop_event

    if stop_event is not None:
        stop_event.set()
    if worker is not None and worker is not threading.current_thread():
        worker.join(timeout)

    with _LIFECYCLE_LOCK:
        if _watcher_thread is worker and (
            worker is None or not worker.is_alive()
        ):
            _watcher_thread = None
            _stop_event = None
            _watched_path = None
            _last_worker_error = None


atexit.register(_stop)

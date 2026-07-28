from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from watchfiles import Change

import codebase_indexer.watcher as watcher
from codebase_indexer.dirty_flag import DIRTY


@pytest.fixture(autouse=True)
def reset_watcher_state():
    watcher._stop()
    DIRTY.check_and_clear()
    yield
    watcher._stop()
    DIRTY.check_and_clear()


def _blocking_watch(ready: threading.Event):
    def fake_watch(*paths, stop_event, **kwargs):
        ready.set()
        while not stop_event.wait(0.01):
            if False:
                yield set()

    return fake_watch


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_start_is_idempotent_for_same_repository(monkeypatch, tmp_path):
    ready = threading.Event()
    monkeypatch.setattr(watcher, "watch", _blocking_watch(ready))

    first = watcher.start(tmp_path)
    assert ready.wait(1)
    second = watcher.start(tmp_path)

    assert first == {
        "status": "started",
        "repo_path": str(tmp_path.resolve()),
        "watcher_running": True,
        "dirty": True,
    }
    assert second == {**first, "status": "already_running"}


def test_start_rejects_different_repository(monkeypatch, tmp_path):
    first_repo = tmp_path / "first"
    second_repo = tmp_path / "second"
    first_repo.mkdir()
    second_repo.mkdir()
    ready = threading.Event()
    monkeypatch.setattr(watcher, "watch", _blocking_watch(ready))

    watcher.start(first_repo)
    assert ready.wait(1)
    DIRTY.check_and_clear()

    with pytest.raises(ValueError, match="different repository"):
        watcher.start(second_repo)

    assert DIRTY.is_set() is False


def test_start_replaces_dead_worker_state(monkeypatch, tmp_path):
    dead_worker = threading.Thread(target=lambda: None)
    dead_worker.start()
    dead_worker.join()
    watcher._watcher_thread = dead_worker
    watcher._watched_path = tmp_path.resolve()
    ready = threading.Event()
    monkeypatch.setattr(watcher, "watch", _blocking_watch(ready))

    result = watcher.start(tmp_path)

    assert ready.wait(1)
    assert result["status"] == "started"
    assert result["watcher_running"] is True


def test_worker_marks_dirty_for_candidate_change(monkeypatch, tmp_path):
    release_change = threading.Event()

    def fake_watch(*paths, stop_event, **kwargs):
        release_change.wait(1)
        yield {(Change.added, str(tmp_path / "module.py"))}
        while not stop_event.wait(0.01):
            pass

    monkeypatch.setattr(watcher, "watch", fake_watch)
    watcher.start(tmp_path)
    DIRTY.check_and_clear()

    release_change.set()

    assert _wait_until(DIRTY.is_set)


def test_worker_failure_marks_dirty_and_stops(monkeypatch, tmp_path):
    release_failure = threading.Event()

    def failing_watch(*paths, **kwargs):
        release_failure.wait(1)
        raise RuntimeError("backend failed")
        yield

    monkeypatch.setattr(watcher, "watch", failing_watch)
    watcher.start(tmp_path)
    DIRTY.check_and_clear()

    release_failure.set()

    assert _wait_until(lambda: not watcher.is_running(tmp_path))
    assert DIRTY.is_set() is True
    assert isinstance(watcher._last_worker_error, RuntimeError)


def test_get_status_rejects_missing_and_dead_worker(tmp_path):
    with pytest.raises(ValueError, match="not running"):
        watcher.get_status(tmp_path)

    dead_worker = threading.Thread(target=lambda: None)
    dead_worker.start()
    dead_worker.join()
    watcher._watcher_thread = dead_worker
    watcher._watched_path = tmp_path.resolve()

    with pytest.raises(ValueError, match="not running"):
        watcher.get_status(tmp_path)


def test_change_classification_is_conservative_for_deletes(tmp_path):
    assert watcher._changes_affect_index(
        {(Change.modified, "module.py")}, tmp_path
    )
    assert watcher._changes_affect_index(
        {(Change.modified, str(tmp_path / "module.py"))}, tmp_path
    )
    assert not watcher._changes_affect_index(
        {(Change.modified, str(tmp_path / "image.png"))}, tmp_path
    )
    assert watcher._changes_affect_index(
        {(Change.deleted, str(tmp_path / "image.png"))}, tmp_path
    )
    assert not watcher._changes_affect_index(
        {(Change.deleted, str(tmp_path.parent / "outside.py"))}, tmp_path
    )
    assert not watcher._changes_affect_index(
        {(Change.deleted, str(tmp_path / ".git" / "index"))}, tmp_path
    )


def test_stop_signals_and_joins_worker(monkeypatch, tmp_path):
    ready = threading.Event()
    monkeypatch.setattr(watcher, "watch", _blocking_watch(ready))
    watcher.start(tmp_path)
    assert ready.wait(1)

    watcher._stop()

    assert watcher.is_running(tmp_path) is False
    assert watcher._watcher_thread is None


def test_stop_does_not_clear_watcher_started_while_old_worker_joins(
    monkeypatch,
    tmp_path,
):
    ready = threading.Event()
    monkeypatch.setattr(watcher, "watch", _blocking_watch(ready))

    class DeadWorker:
        def is_alive(self):
            return False

        def join(self, timeout):
            watcher.start(tmp_path)

    old_worker = DeadWorker()
    watcher._watcher_thread = old_worker
    watcher._stop_event = threading.Event()
    watcher._watched_path = tmp_path.resolve()

    watcher._stop()

    assert ready.wait(1)
    assert watcher._watcher_thread is not old_worker
    assert watcher.is_running(tmp_path) is True


def test_real_watchfiles_backend_marks_repository_dirty(monkeypatch, tmp_path):
    # Sandboxed test runners may suppress native FSEvents delivery.
    monkeypatch.setenv("WATCHFILES_FORCE_POLLING", "true")
    watcher.start(tmp_path)
    DIRTY.check_and_clear()
    file_path = tmp_path / "module.py"
    deadline = time.monotonic() + 3
    revision = 0

    while not DIRTY.is_set() and time.monotonic() < deadline:
        revision += 1
        file_path.write_text(f"revision = {revision}\n", encoding="utf-8")
        time.sleep(0.05)

    assert DIRTY.is_set() is True

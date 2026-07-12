import json
from dataclasses import dataclass, field
from pathlib import Path
import threading

import pytest

import codebase_indexer.indexer as indexer
from codebase_indexer.hashing import FileChangedDuringHashingError, hash_file
from codebase_indexer.indexer import IndexPartialFailureError, index_repository


@dataclass
class FakeIndexStore:
    index_dir: Path
    fail_relative_paths: set[str] = field(default_factory=set)
    upserted_relative_paths: list[str] = field(default_factory=list)
    upsert_chunk_counts: list[int] = field(default_factory=list)
    upsert_thread_ids: list[int] = field(default_factory=list)

    def upsert_chunks(self, chunks):
        self.upsert_chunk_counts.append(len(chunks))
        self.upsert_thread_ids.append(threading.get_ident())
        if not chunks:
            return
        relative_path = chunks[0].metadata["relative_path"]
        if relative_path in self.fail_relative_paths:
            raise RuntimeError("embedding error")
        self.upserted_relative_paths.append(relative_path)


def _make_repo(tmp_path, files):
    repo_path = tmp_path / "repo"
    for relative_path, content in files.items():
        file_path = repo_path / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    repo_path.mkdir(exist_ok=True)
    return repo_path


def _payload_from_error(exc_info):
    return json.loads(str(exc_info.value))


def test_index_repository_indexes_eligible_files_and_returns_counts(tmp_path):
    repo_path = _make_repo(
        tmp_path,
        {
            "src/a.py": "a\n",
            "src/b.py": "b\n",
            "notes.txt": "skip\n",
        },
    )
    store = FakeIndexStore(repo_path / ".codebase-index")

    result = index_repository(store, repo_path)

    assert result == {
        "status": "initialized",
        "repo_path": str(repo_path.resolve()),
        "index_path": str((repo_path / ".codebase-index").resolve()),
        "created": True,
        "files_indexed": 2,
        "chunks_indexed": 2,
        "files_skipped": 1,
    }
    assert set(store.upserted_relative_paths) == {"src/a.py", "src/b.py"}


def test_index_repository_empty_repo_returns_zero_counts(tmp_path):
    repo_path = _make_repo(tmp_path, {"notes.txt": "skip\n"})
    store = FakeIndexStore(repo_path / ".codebase-index")

    result = index_repository(store, repo_path)

    assert result["created"] is True
    assert result["files_indexed"] == 0
    assert result["chunks_indexed"] == 0
    assert result["files_skipped"] == 1
    assert store.upserted_relative_paths == []


def test_index_repository_counts_empty_file_with_zero_chunks(tmp_path):
    repo_path = _make_repo(tmp_path, {"empty.py": ""})
    store = FakeIndexStore(repo_path / ".codebase-index")

    result = index_repository(store, repo_path)

    assert result["files_indexed"] == 1
    assert result["chunks_indexed"] == 0
    assert store.upsert_chunk_counts == [0]


def test_index_repository_records_preparation_failure_and_continues(
    monkeypatch,
    tmp_path,
):
    repo_path = _make_repo(
        tmp_path,
        {
            "src/broken.py": "broken\n",
            "src/working.py": "working\n",
        },
    )
    store = FakeIndexStore(repo_path / ".codebase-index")
    real_hash_file = hash_file

    def fail_for_broken_file(file_path):
        if file_path.name == "broken.py":
            raise FileNotFoundError("file disappeared")
        return real_hash_file(file_path)

    monkeypatch.setattr(indexer, "hash_file", fail_for_broken_file)

    with pytest.raises(IndexPartialFailureError) as exc_info:
        index_repository(store, repo_path)

    payload = _payload_from_error(exc_info)
    assert payload["files_indexed"] == 1
    assert payload["chunks_indexed"] == 1
    assert payload["files_skipped"] == 0
    assert payload["files_failed"] == 1
    assert payload["failures"] == [
        {"relative_path": "src/broken.py", "reason": "file disappeared"}
    ]
    assert store.upserted_relative_paths == ["src/working.py"]


def test_index_repository_records_file_changed_during_hashing(
    monkeypatch,
    tmp_path,
):
    repo_path = _make_repo(tmp_path, {"changed.py": "changed\n"})
    store = FakeIndexStore(repo_path / ".codebase-index")

    def fail_hashing(_file_path):
        raise FileChangedDuringHashingError("changed during hashing")

    monkeypatch.setattr(indexer, "hash_file", fail_hashing)

    with pytest.raises(IndexPartialFailureError) as exc_info:
        index_repository(store, repo_path)

    payload = _payload_from_error(exc_info)
    assert payload["failures"] == [
        {"relative_path": "changed.py", "reason": "changed during hashing"}
    ]


def test_index_repository_records_permission_failure_during_preparation(
    monkeypatch,
    tmp_path,
):
    repo_path = _make_repo(tmp_path, {"locked.py": "locked\n"})
    store = FakeIndexStore(repo_path / ".codebase-index")

    def fail_hashing(_file_path):
        raise PermissionError("permission denied")

    monkeypatch.setattr(indexer, "hash_file", fail_hashing)

    with pytest.raises(IndexPartialFailureError) as exc_info:
        index_repository(store, repo_path)

    payload = _payload_from_error(exc_info)
    assert payload["files_indexed"] == 0
    assert payload["chunks_indexed"] == 0
    assert payload["failures"] == [
        {"relative_path": "locked.py", "reason": "permission denied"}
    ]


def test_index_repository_records_write_failure_and_indexes_remaining_files(tmp_path):
    repo_path = _make_repo(
        tmp_path,
        {
            "a.py": "a\n",
            "b.py": "b\n",
            "c.py": "c\n",
        },
    )
    store = FakeIndexStore(
        repo_path / ".codebase-index",
        fail_relative_paths={"b.py"},
    )

    with pytest.raises(IndexPartialFailureError) as exc_info:
        index_repository(store, repo_path)

    payload = _payload_from_error(exc_info)
    assert payload["files_indexed"] == 2
    assert payload["chunks_indexed"] == 2
    assert payload["failures"] == [
        {"relative_path": "b.py", "reason": "index write failed: embedding error"}
    ]
    assert set(store.upserted_relative_paths) == {"a.py", "c.py"}


def test_index_repository_sorts_failures_by_relative_path(tmp_path):
    repo_path = _make_repo(
        tmp_path,
        {
            "z.py": "z\n",
            "a.py": "a\n",
            "m.py": "m\n",
        },
    )
    store = FakeIndexStore(
        repo_path / ".codebase-index",
        fail_relative_paths={"z.py", "a.py", "m.py"},
    )

    with pytest.raises(IndexPartialFailureError) as exc_info:
        index_repository(store, repo_path)

    payload = _payload_from_error(exc_info)
    assert payload["files_indexed"] == 0
    assert payload["chunks_indexed"] == 0
    assert payload["files_failed"] == 3
    assert [failure["relative_path"] for failure in payload["failures"]] == [
        "a.py",
        "m.py",
        "z.py",
    ]


def test_index_repository_serializes_store_writes_on_calling_thread(tmp_path):
    repo_path = _make_repo(
        tmp_path,
        {
            "a.py": "a\n",
            "b.py": "b\n",
        },
    )
    store = FakeIndexStore(repo_path / ".codebase-index")
    calling_thread_id = threading.get_ident()

    index_repository(store, repo_path)

    assert store.upsert_thread_ids == [calling_thread_id, calling_thread_id]


def test_index_repository_uses_configured_batch_size(monkeypatch, tmp_path):
    repo_path = _make_repo(
        tmp_path,
        {f"file_{index}.py": f"{index}\n" for index in range(3)},
    )
    store = FakeIndexStore(repo_path / ".codebase-index")
    submitted_files = []
    real_prepare_file = indexer._prepare_file

    def record_prepare_file(file_path, repo_path, relative_path):
        submitted_files.append(relative_path)
        return real_prepare_file(file_path, repo_path, relative_path)

    monkeypatch.setattr(indexer, "_prepare_file", record_prepare_file)
    monkeypatch.setattr(indexer.config, "DEFAULT_INDEX_BATCH_SIZE", 2)

    result = index_repository(store, repo_path)

    assert result["files_indexed"] == 3
    assert sorted(submitted_files) == [
        "file_0.py",
        "file_1.py",
        "file_2.py",
    ]

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

import codebase_indexer.status as status
from codebase_indexer.hashing import FileChangedDuringHashingError, hash_file
from codebase_indexer.status import get_repository_index_status


@dataclass
class FakeIndexStore:
    index_dir: Path
    metadata: list[dict[str, object] | None]
    chunk_count: int | None = None

    def get_indexed_file_metadata(self) -> list[dict[str, object] | None]:
        return self.metadata

    def collection_count(self) -> int:
        return self.chunk_count if self.chunk_count is not None else len(self.metadata)


def _metadata(relative_path: str, file_hash: str) -> dict[str, object]:
    return {"relative_path": relative_path, "file_hash": file_hash}


def _store(repo_path: Path, metadata: list[dict[str, object] | None]):
    return FakeIndexStore(repo_path / ".codebase-index", metadata)


def test_get_repository_index_status_returns_clean_for_matching_file(tmp_path):
    file_path = tmp_path / "module.py"
    file_path.write_text("content\n", encoding="utf-8")
    store = _store(tmp_path, [_metadata("module.py", hash_file(file_path))])

    result = get_repository_index_status(store, tmp_path)

    assert result == {
        "status": "clean",
        "repo_path": str(tmp_path.resolve()),
        "index_path": str(store.index_dir),
        "collection_name": "codebase_indexer",
        "indexed_files": 1,
        "indexed_chunks": 1,
        "files_to_reindex": [],
        "files_to_delete": [],
        "files_with_errors": [],
    }


def test_get_repository_index_status_reports_changed_and_new_files(tmp_path):
    changed_path = tmp_path / "changed.py"
    new_path = tmp_path / "new.py"
    changed_path.write_text("changed\n", encoding="utf-8")
    new_path.write_text("new\n", encoding="utf-8")
    store = _store(tmp_path, [_metadata("changed.py", "old-hash")])

    result = get_repository_index_status(store, tmp_path)

    assert result["files_to_reindex"] == [
        {"relative_path": "changed.py", "reason": "content_changed"},
        {"relative_path": "new.py", "reason": "not_indexed"},
    ]


def test_get_repository_index_status_reports_missing_indexed_file(tmp_path):
    store = _store(tmp_path, [_metadata("deleted.py", "old-hash")])

    result = get_repository_index_status(store, tmp_path)

    assert result["files_to_delete"] == [
        {"relative_path": "deleted.py", "reason": "missing"}
    ]


def test_get_repository_index_status_reports_no_longer_indexable_file(tmp_path):
    file_path = tmp_path / "image.png"
    file_path.write_bytes(b"content")
    store = _store(tmp_path, [_metadata("image.png", "old-hash")])

    result = get_repository_index_status(store, tmp_path)

    assert result["files_to_delete"] == [
        {"relative_path": "image.png", "reason": "no_longer_indexable"}
    ]


def test_get_repository_index_status_reports_rename_as_two_actions(tmp_path):
    new_path = tmp_path / "new.py"
    new_path.write_text("content\n", encoding="utf-8")
    store = _store(tmp_path, [_metadata("old.py", "old-hash")])

    result = get_repository_index_status(store, tmp_path)

    assert result["files_to_delete"] == [
        {"relative_path": "old.py", "reason": "missing"}
    ]
    assert result["files_to_reindex"] == [
        {"relative_path": "new.py", "reason": "not_indexed"}
    ]


def test_get_repository_index_status_reports_conflicting_hashes(tmp_path):
    file_path = tmp_path / "module.py"
    file_path.write_text("content\n", encoding="utf-8")
    store = _store(
        tmp_path,
        [
            _metadata("module.py", "first-hash"),
            _metadata("module.py", "second-hash"),
        ],
    )

    result = get_repository_index_status(store, tmp_path)

    assert result["files_to_reindex"] == [
        {"relative_path": "module.py", "reason": "inconsistent_index"}
    ]
    assert result["indexed_files"] == 1
    assert result["indexed_chunks"] == 2


@pytest.mark.parametrize(
    ("metadata", "relative_path", "reason"),
    [
        (None, "<metadata:0>", "missing chunk metadata"),
        ({"file_hash": "hash"}, "<metadata:0>", "missing indexed relative_path"),
        ({"relative_path": "module.py"}, "module.py", "missing indexed file_hash"),
    ],
)
def test_get_repository_index_status_reports_malformed_metadata(
    tmp_path,
    metadata,
    relative_path,
    reason,
):
    store = _store(tmp_path, [metadata])

    result = get_repository_index_status(store, tmp_path)

    assert result["files_to_delete"] == []
    assert {"relative_path": relative_path, "reason": reason} in result[
        "files_with_errors"
    ]


def test_malformed_indexed_path_is_not_also_reported_for_reindex(tmp_path):
    (tmp_path / "module.py").write_text("content\n", encoding="utf-8")
    store = _store(tmp_path, [{"relative_path": "module.py"}])

    result = get_repository_index_status(store, tmp_path)

    assert result["files_to_reindex"] == []
    assert result["files_to_delete"] == []
    assert result["files_with_errors"] == [
        {"relative_path": "module.py", "reason": "missing indexed file_hash"}
    ]


@pytest.mark.parametrize(
    ("relative_path", "reason"),
    [
        ("./module.py", "indexed relative path is not normalized"),
        ("../outside.py", "resolves outside repo_path"),
    ],
)
def test_unsafe_indexed_path_is_error_without_action(
    tmp_path,
    relative_path,
    reason,
):
    store = _store(tmp_path, [_metadata(relative_path, "old-hash")])

    result = get_repository_index_status(store, tmp_path)

    assert result["files_to_reindex"] == []
    assert result["files_to_delete"] == []
    assert reason in result["files_with_errors"][0]["reason"]


def test_get_repository_index_status_reports_hashing_error_without_action(
    monkeypatch,
    tmp_path,
):
    file_path = tmp_path / "module.py"
    file_path.write_text("content\n", encoding="utf-8")
    store = _store(tmp_path, [_metadata("module.py", "old-hash")])

    def raise_changed(path):
        raise FileChangedDuringHashingError("file changed")

    monkeypatch.setattr(status, "hash_file", raise_changed)

    result = get_repository_index_status(store, tmp_path)

    assert result["files_to_reindex"] == []
    assert result["files_to_delete"] == []
    assert result["files_with_errors"] == [
        {"relative_path": "module.py", "reason": "file changed"}
    ]


def test_get_repository_index_status_reports_disappearance_during_hashing(
    monkeypatch,
    tmp_path,
):
    file_path = tmp_path / "module.py"
    file_path.write_text("content\n", encoding="utf-8")
    store = _store(tmp_path, [_metadata("module.py", "old-hash")])

    def raise_missing(path):
        raise FileNotFoundError(path)

    monkeypatch.setattr(status, "hash_file", raise_missing)

    result = get_repository_index_status(store, tmp_path)

    assert result["files_to_delete"] == [
        {"relative_path": "module.py", "reason": "missing"}
    ]
    assert result["files_with_errors"] == []


def test_get_repository_index_status_reports_disappearance_during_filtering(
    monkeypatch,
    tmp_path,
):
    file_path = tmp_path / "module.py"
    file_path.write_text("content\n", encoding="utf-8")
    store = _store(tmp_path, [_metadata("module.py", "old-hash")])

    def raise_missing(file_path, repo_path):
        raise FileNotFoundError(file_path)

    monkeypatch.setattr(status, "should_index_file", raise_missing)

    result = get_repository_index_status(store, tmp_path)

    assert result["files_to_delete"] == [
        {"relative_path": "module.py", "reason": "missing"}
    ]
    assert result["files_with_errors"] == []


def test_get_repository_index_status_reports_hash_read_error(
    monkeypatch,
    tmp_path,
):
    file_path = tmp_path / "module.py"
    file_path.write_text("content\n", encoding="utf-8")
    store = _store(tmp_path, [_metadata("module.py", "old-hash")])

    def raise_read_error(path):
        raise OSError("disk read error")

    monkeypatch.setattr(status, "hash_file", raise_read_error)

    result = get_repository_index_status(store, tmp_path)

    assert result["files_to_delete"] == []
    assert result["files_to_reindex"] == []
    assert result["files_with_errors"] == [
        {"relative_path": "module.py", "reason": "disk read error"}
    ]


def test_get_repository_index_status_reports_filtering_permission_error(
    monkeypatch,
    tmp_path,
):
    file_path = tmp_path / "module.py"
    file_path.write_text("content\n", encoding="utf-8")
    store = _store(tmp_path, [_metadata("module.py", "old-hash")])

    def raise_permission(file_path, repo_path):
        raise PermissionError("permission denied")

    monkeypatch.setattr(status, "should_index_file", raise_permission)

    result = get_repository_index_status(store, tmp_path)

    assert result["files_to_delete"] == []
    assert result["files_with_errors"] == [
        {"relative_path": "module.py", "reason": "permission denied"}
    ]


def test_get_repository_index_status_sorts_action_lists(tmp_path):
    for filename in ["z.py", "a.py"]:
        (tmp_path / filename).write_text("content\n", encoding="utf-8")
    store = _store(
        tmp_path,
        [
            _metadata("z-old.py", "hash"),
            _metadata("a-old.py", "hash"),
        ],
    )

    result = get_repository_index_status(store, tmp_path)

    assert [item["relative_path"] for item in result["files_to_reindex"]] == [
        "a.py",
        "z.py",
    ]
    assert [item["relative_path"] for item in result["files_to_delete"]] == [
        "a-old.py",
        "z-old.py",
    ]


def test_get_repository_index_status_reports_empty_file_as_not_indexed(tmp_path):
    (tmp_path / "empty.py").write_text("", encoding="utf-8")
    store = _store(tmp_path, [])

    result = get_repository_index_status(store, tmp_path)

    assert result["files_to_reindex"] == [
        {"relative_path": "empty.py", "reason": "not_indexed"}
    ]


def test_status_public_surface():
    assert status.__all__ == ["get_repository_index_status"]

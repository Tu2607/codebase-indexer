from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import codebase_indexer.reindexer as reindexer
from codebase_indexer.hashing import FileChangedDuringHashingError, hash_file
from codebase_indexer.reindexer import reindex_single_file


@dataclass
class FakeIndexStore:
    old_ids: list[str] = field(default_factory=list)
    upsert_error: Exception | None = None
    delete_error: Exception | None = None
    events: list[tuple[str, object]] = field(default_factory=list)

    def delete_chunks_for_file(self, relative_path: str) -> int:
        self.events.append(("delete_for_file", relative_path))
        removed_count = len(self.old_ids)
        self.old_ids = []
        return removed_count

    def get_chunk_ids_for_file(self, relative_path: str) -> list[str]:
        self.events.append(("get_chunk_ids", relative_path))
        return list(self.old_ids)

    def upsert_chunks(self, chunks: list[object]) -> None:
        self.events.append(("upsert", chunks))
        if self.upsert_error is not None:
            raise self.upsert_error

    def delete_chunks_by_ids(self, ids: list[str]) -> None:
        self.events.append(("delete_by_ids", ids))
        if self.delete_error is not None:
            raise self.delete_error


def test_reindex_single_file_replaces_stale_chunks_after_upsert(tmp_path):
    repo_path = tmp_path / "repo"
    file_path = repo_path / "src" / "module.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("first\nsecond\n", encoding="utf-8")
    store = FakeIndexStore(old_ids=["old-chunk"])

    result = reindex_single_file(store, "src/module.py", repo_path)

    upserted_chunks = store.events[1][1]
    assert result == {
        "status": "reindexed",
        "relative_path": "src/module.py",
        "file_hash": hash_file(file_path),
        "chunks_added": 1,
        "chunks_removed": 1,
    }
    assert store.events[0] == ("get_chunk_ids", "src/module.py")
    assert store.events[1][0] == "upsert"
    assert store.events[2] == ("delete_by_ids", ["old-chunk"])
    assert [chunk.metadata["relative_path"] for chunk in upserted_chunks] == [
        "src/module.py"
    ]


def test_reindex_single_file_is_idempotent_when_chunk_ids_are_unchanged(tmp_path):
    repo_path = tmp_path / "repo"
    file_path = repo_path / "module.py"
    repo_path.mkdir()
    file_path.write_text("content\n", encoding="utf-8")
    first_store = FakeIndexStore()

    first_result = reindex_single_file(first_store, "module.py", repo_path)
    current_ids = [chunk.id for chunk in first_store.events[1][1]]
    second_store = FakeIndexStore(old_ids=current_ids)

    second_result = reindex_single_file(second_store, "module.py", repo_path)

    assert first_result["file_hash"] == second_result["file_hash"]
    assert second_result["chunks_added"] == 0
    assert second_result["chunks_removed"] == 0
    assert second_store.events[2] == ("delete_by_ids", [])


def test_reindex_single_file_removes_chunks_for_missing_file(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    store = FakeIndexStore(old_ids=["old-first", "old-second"])

    result = reindex_single_file(store, "src/deleted.py", repo_path)

    assert result == {
        "status": "deleted",
        "relative_path": "src/deleted.py",
        "chunks_removed": 2,
    }
    assert store.events == [("delete_for_file", "src/deleted.py")]


def test_reindex_single_file_removes_chunks_for_unindexable_file(tmp_path):
    repo_path = tmp_path / "repo"
    file_path = repo_path / "image.png"
    repo_path.mkdir()
    file_path.write_bytes(b"content")
    store = FakeIndexStore(old_ids=["old-chunk"])

    result = reindex_single_file(store, file_path.name, repo_path)

    assert result == {
        "status": "removed_unindexable",
        "relative_path": "image.png",
        "reason": "unsupported file type: image.png",
        "chunks_removed": 1,
    }
    assert store.events == [("delete_for_file", "image.png")]


def test_reindex_single_file_reindexes_empty_file_and_removes_old_chunks(tmp_path):
    repo_path = tmp_path / "repo"
    file_path = repo_path / "empty.py"
    repo_path.mkdir()
    file_path.write_text("", encoding="utf-8")
    store = FakeIndexStore(old_ids=["old-chunk"])

    result = reindex_single_file(store, "empty.py", repo_path)

    assert result == {
        "status": "reindexed",
        "relative_path": "empty.py",
        "file_hash": hash_file(file_path),
        "chunks_added": 0,
        "chunks_removed": 1,
    }
    assert store.events == [
        ("get_chunk_ids", "empty.py"),
        ("upsert", []),
        ("delete_by_ids", ["old-chunk"]),
    ]


def test_reindex_single_file_leaves_index_unchanged_when_hashing_fails(
    monkeypatch,
    tmp_path,
):
    repo_path = tmp_path / "repo"
    file_path = repo_path / "module.py"
    repo_path.mkdir()
    file_path.write_text("content\n", encoding="utf-8")
    store = FakeIndexStore(old_ids=["old-chunk"])

    def raise_file_changed(path):
        raise FileChangedDuringHashingError("file changed")

    monkeypatch.setattr(reindexer, "hash_file", raise_file_changed)

    result = reindex_single_file(store, "module.py", repo_path)

    assert result == {
        "status": "hash_failed",
        "relative_path": "module.py",
        "retryable": True,
        "message": "File changed during hashing; retry after the write completes",
    }
    assert store.events == []


def test_reindex_single_file_deletes_chunks_when_file_disappears_during_filtering(
    monkeypatch,
    tmp_path,
):
    repo_path = tmp_path / "repo"
    file_path = repo_path / "module.py"
    repo_path.mkdir()
    file_path.write_text("content\n", encoding="utf-8")
    store = FakeIndexStore(old_ids=["old-chunk"])

    def raise_file_not_found(file_path, repo_path):
        raise FileNotFoundError(file_path)

    monkeypatch.setattr(reindexer, "should_index_file", raise_file_not_found)

    result = reindex_single_file(store, "module.py", repo_path)

    assert result == {
        "status": "deleted",
        "relative_path": "module.py",
        "chunks_removed": 1,
    }
    assert store.events == [("delete_for_file", "module.py")]


def test_reindex_single_file_deletes_chunks_when_file_disappears_during_hashing(
    monkeypatch,
    tmp_path,
):
    repo_path = tmp_path / "repo"
    file_path = repo_path / "module.py"
    repo_path.mkdir()
    file_path.write_text("content\n", encoding="utf-8")
    store = FakeIndexStore(old_ids=["old-chunk"])

    def raise_file_not_found(path):
        raise FileNotFoundError(path)

    monkeypatch.setattr(reindexer, "hash_file", raise_file_not_found)

    result = reindex_single_file(store, "module.py", repo_path)

    assert result == {
        "status": "deleted",
        "relative_path": "module.py",
        "chunks_removed": 1,
    }
    assert store.events == [("delete_for_file", "module.py")]


def test_reindex_single_file_deletes_chunks_when_file_disappears_during_chunking(
    monkeypatch,
    tmp_path,
):
    repo_path = tmp_path / "repo"
    file_path = repo_path / "module.py"
    repo_path.mkdir()
    file_path.write_text("content\n", encoding="utf-8")
    store = FakeIndexStore(old_ids=["old-chunk"])

    def raise_file_not_found(*args, **kwargs):
        raise FileNotFoundError(args[0])

    monkeypatch.setattr(reindexer, "chunk_by_lines", raise_file_not_found)

    result = reindex_single_file(store, "module.py", repo_path)

    assert result == {
        "status": "deleted",
        "relative_path": "module.py",
        "chunks_removed": 1,
    }
    assert store.events == [("delete_for_file", "module.py")]


def test_reindex_single_file_rejects_file_outside_repo_before_store_access(tmp_path):
    repo_path = tmp_path / "repo"
    outside_path = tmp_path / "outside.py"
    repo_path.mkdir()
    outside_path.write_text("content\n", encoding="utf-8")
    store = FakeIndexStore(old_ids=["old-chunk"])

    with pytest.raises(ValueError, match="resolves outside repo_path"):
        reindex_single_file(store, str(outside_path), repo_path)

    assert store.events == []


def test_reindex_single_file_preserves_old_chunks_when_upsert_fails(tmp_path):
    repo_path = tmp_path / "repo"
    file_path = repo_path / "module.py"
    repo_path.mkdir()
    file_path.write_text("content\n", encoding="utf-8")
    store = FakeIndexStore(
        old_ids=["old-chunk"],
        upsert_error=RuntimeError("embedding failed"),
    )

    with pytest.raises(RuntimeError, match="embedding failed"):
        reindex_single_file(store, "module.py", repo_path)

    assert store.events[0] == ("get_chunk_ids", "module.py")
    assert store.events[1][0] == "upsert"
    assert len(store.events) == 2


def test_reindex_single_file_propagates_delete_failure_after_upsert(tmp_path):
    repo_path = tmp_path / "repo"
    file_path = repo_path / "module.py"
    repo_path.mkdir()
    file_path.write_text("content\n", encoding="utf-8")
    store = FakeIndexStore(
        old_ids=["old-chunk"],
        delete_error=RuntimeError("delete failed"),
    )

    with pytest.raises(RuntimeError, match="delete failed"):
        reindex_single_file(store, "module.py", repo_path)

    assert store.events[0] == ("get_chunk_ids", "module.py")
    assert store.events[1][0] == "upsert"
    assert store.events[2] == ("delete_by_ids", ["old-chunk"])


def test_reindex_single_file_preserves_old_chunks_when_chunking_fails(
    monkeypatch,
    tmp_path,
):
    repo_path = tmp_path / "repo"
    file_path = repo_path / "module.py"
    repo_path.mkdir()
    file_path.write_text("content\n", encoding="utf-8")
    store = FakeIndexStore(old_ids=["old-chunk"])

    def raise_permission_error(*args, **kwargs):
        raise PermissionError("cannot read file")

    monkeypatch.setattr(reindexer, "chunk_by_lines", raise_permission_error)

    with pytest.raises(PermissionError, match="cannot read file"):
        reindex_single_file(store, "module.py", repo_path)

    assert store.events == []


def test_reindexer_public_surface():
    assert reindexer.__all__ == ["reindex_single_file"]

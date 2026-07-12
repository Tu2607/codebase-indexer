from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import codebase_indexer.deleter as deleter
from codebase_indexer.deleter import delete_indexed_file


@dataclass
class FakeIndexStore:
    chunks_removed: int = 0
    delete_error: Exception | None = None
    events: list[tuple[str, str]] = field(default_factory=list)

    def delete_chunks_for_file(self, relative_path: str) -> int:
        self.events.append(("delete_for_file", relative_path))
        if self.delete_error is not None:
            raise self.delete_error
        return self.chunks_removed


def test_delete_indexed_file_deletes_existing_relative_path(tmp_path):
    repo_path = tmp_path / "repo"
    file_path = repo_path / "src" / "module.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("content\n", encoding="utf-8")
    store = FakeIndexStore(chunks_removed=2)

    result = delete_indexed_file(store, "src/module.py", repo_path)

    assert result == {
        "status": "deleted",
        "relative_path": "src/module.py",
        "chunks_removed": 2,
    }
    assert store.events == [("delete_for_file", "src/module.py")]


def test_delete_indexed_file_accepts_missing_path(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    store = FakeIndexStore(chunks_removed=1)

    result = delete_indexed_file(store, "src/deleted.py", repo_path)

    assert result["relative_path"] == "src/deleted.py"
    assert result["chunks_removed"] == 1
    assert store.events == [("delete_for_file", "src/deleted.py")]


def test_delete_indexed_file_accepts_absolute_path_inside_repo(tmp_path):
    repo_path = tmp_path / "repo"
    file_path = repo_path / "module.py"
    repo_path.mkdir()
    store = FakeIndexStore()

    result = delete_indexed_file(store, str(file_path), repo_path)

    assert result == {
        "status": "deleted",
        "relative_path": "module.py",
        "chunks_removed": 0,
    }
    assert store.events == [("delete_for_file", "module.py")]


def test_delete_indexed_file_propagates_store_failure(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    store = FakeIndexStore(delete_error=RuntimeError("delete failed"))

    with pytest.raises(RuntimeError, match="delete failed"):
        delete_indexed_file(store, "module.py", repo_path)

    assert store.events == [("delete_for_file", "module.py")]


@pytest.mark.parametrize("file_path", [".", "../outside.py"])
def test_delete_indexed_file_rejects_invalid_target_before_store_access(
    tmp_path,
    file_path,
):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    store = FakeIndexStore(chunks_removed=1)

    with pytest.raises(ValueError):
        delete_indexed_file(store, file_path, repo_path)

    assert store.events == []


def test_deleter_public_surface():
    assert deleter.__all__ == ["delete_indexed_file"]

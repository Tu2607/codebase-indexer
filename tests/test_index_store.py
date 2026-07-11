import sqlite3
from unittest.mock import Mock

import chromadb
import pytest
from chromadb.errors import InternalError, NotFoundError

from codebase_indexer.chunker import TextChunk
from codebase_indexer.config import (
    DEFAULT_COLLECTION_NAME,
    DEFAULT_INDEX_DIR_NAME,
    SKIP_DIRECTORIES,
)
from codebase_indexer.index_store import (
    IndexCorruptedError,
    IndexNotInitializedError,
    IndexStore,
)

EMBEDDING_DIMENSIONS = 384


class FakeEmbeddingFunction:
    @staticmethod
    def name() -> str:
        return "default"

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [[0.0] * EMBEDDING_DIMENSIONS for _ in input]


def _embedding(value: float) -> list[float]:
    return [value] * EMBEDDING_DIMENSIONS


def test_index_store_creates_repository_local_index_directory(tmp_path):
    store = IndexStore(tmp_path)

    assert store.index_dir == tmp_path.resolve() / DEFAULT_INDEX_DIR_NAME
    assert store.index_dir.is_dir()


def test_index_store_opens_configured_collection(tmp_path):
    store = IndexStore(tmp_path)

    assert store.collection.name == DEFAULT_COLLECTION_NAME


def test_index_store_starts_with_an_empty_collection(tmp_path):
    store = IndexStore(tmp_path)

    assert store.collection_count() == 0


def test_index_store_reopens_persisted_collection_data(tmp_path):
    first_store = IndexStore(tmp_path)
    first_store.collection.add(
        ids=["test-chunk"],
        embeddings=[_embedding(0.1)],
        documents=["persisted document"],
        metadatas=[{"kind": "test"}],
    )

    second_store = IndexStore(tmp_path)
    persisted = second_store.collection.get(ids=["test-chunk"])

    assert second_store.collection_count() == 1
    assert persisted["documents"] == ["persisted document"]
    assert persisted["metadatas"] == [{"kind": "test"}]


def test_index_store_resolves_repository_path(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    unresolved_path = repo_path.parent / "repo" / "."

    store = IndexStore(unresolved_path)

    assert store.repo_path == repo_path.resolve()


def test_index_store_places_index_under_repository(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    store = IndexStore(repo_path)

    assert store.index_dir == store.repo_path / DEFAULT_INDEX_DIR_NAME


def test_index_store_resolves_symlinked_repository_path(tmp_path):
    target_path = tmp_path / "target"
    target_path.mkdir()
    link_path = tmp_path / "repository-link"

    try:
        link_path.symlink_to(target_path, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    store = IndexStore(link_path)

    assert store.repo_path == target_path.resolve()
    assert store.index_dir == target_path.resolve() / DEFAULT_INDEX_DIR_NAME


def test_index_directory_is_reserved_for_file_discovery_skip():
    assert DEFAULT_INDEX_DIR_NAME in SKIP_DIRECTORIES


def test_index_store_rejects_missing_repository_path(tmp_path):
    with pytest.raises(ValueError, match="existing directory"):
        IndexStore(tmp_path / "missing")


def test_index_store_rejects_file_as_repository_path(tmp_path):
    file_path = tmp_path / "not-a-repository"
    file_path.write_text("content\n", encoding="utf-8")

    with pytest.raises(ValueError, match="existing directory"):
        IndexStore(file_path)


def test_is_initialized_is_false_without_index_directory(tmp_path):
    assert not IndexStore.is_initialized(tmp_path)
    assert not (tmp_path / DEFAULT_INDEX_DIR_NAME).exists()


def test_is_initialized_is_false_for_empty_index_directory(tmp_path):
    (tmp_path / DEFAULT_INDEX_DIR_NAME).mkdir()

    assert not IndexStore.is_initialized(tmp_path)


def test_is_initialized_is_true_after_store_creation(tmp_path):
    IndexStore(tmp_path)

    assert IndexStore.is_initialized(tmp_path)


def test_open_existing_rejects_missing_index_without_creating_it(tmp_path):
    with pytest.raises(IndexNotInitializedError, match="index_repo"):
        IndexStore.open_existing(tmp_path)

    assert not (tmp_path / DEFAULT_INDEX_DIR_NAME).exists()


def test_open_existing_rejects_empty_index_directory(tmp_path):
    index_dir = tmp_path / DEFAULT_INDEX_DIR_NAME
    index_dir.mkdir()

    with pytest.raises(IndexNotInitializedError, match="index_repo"):
        IndexStore.open_existing(tmp_path)

    assert list(index_dir.iterdir()) == []


def test_open_existing_wraps_chroma_missing_collection_error(tmp_path):
    index_dir = tmp_path / DEFAULT_INDEX_DIR_NAME
    chromadb.PersistentClient(path=str(index_dir))

    assert IndexStore.is_initialized(tmp_path)

    with pytest.raises(IndexCorruptedError, match="rebuild_index") as exc_info:
        IndexStore.open_existing(tmp_path)

    assert isinstance(exc_info.value.__cause__, NotFoundError)


@pytest.mark.parametrize("error_type", [InternalError, sqlite3.DatabaseError])
def test_open_existing_wraps_database_open_error(tmp_path, monkeypatch, error_type):
    index_dir = tmp_path / DEFAULT_INDEX_DIR_NAME
    index_dir.mkdir()
    (index_dir / "chroma.sqlite3").write_bytes(b"corrupt")
    open_error = error_type("database is corrupt")

    def raise_open_error(*, path):
        raise open_error

    monkeypatch.setattr(chromadb, "PersistentClient", raise_open_error)

    with pytest.raises(IndexCorruptedError, match="rebuild_index") as exc_info:
        IndexStore.open_existing(tmp_path)

    assert exc_info.value.__cause__ is open_error


def test_open_existing_wraps_real_corrupt_chroma_database(tmp_path):
    index_dir = tmp_path / DEFAULT_INDEX_DIR_NAME
    index_dir.mkdir()
    (index_dir / "chroma.sqlite3").write_bytes(b"corrupt")

    with pytest.raises(IndexCorruptedError, match="file is not a database") as exc_info:
        IndexStore.open_existing(tmp_path)

    assert isinstance(exc_info.value.__cause__, InternalError)


def test_open_existing_does_not_wrap_filesystem_open_error(tmp_path, monkeypatch):
    index_dir = tmp_path / DEFAULT_INDEX_DIR_NAME
    index_dir.mkdir()
    (index_dir / "chroma.sqlite3").write_bytes(b"database")
    open_error = OSError("permission denied")

    def raise_open_error(*, path):
        raise open_error

    monkeypatch.setattr(chromadb, "PersistentClient", raise_open_error)

    with pytest.raises(OSError) as exc_info:
        IndexStore.open_existing(tmp_path)

    assert exc_info.value is open_error


def test_open_existing_does_not_wrap_runtime_open_error(tmp_path, monkeypatch):
    index_dir = tmp_path / DEFAULT_INDEX_DIR_NAME
    index_dir.mkdir()
    (index_dir / "chroma.sqlite3").write_bytes(b"database")
    open_error = RuntimeError("dependency mismatch")

    def raise_open_error(*, path):
        raise open_error

    monkeypatch.setattr(chromadb, "PersistentClient", raise_open_error)

    with pytest.raises(RuntimeError) as exc_info:
        IndexStore.open_existing(tmp_path)

    assert exc_info.value is open_error


def test_open_existing_reopens_collection(tmp_path):
    original = IndexStore(tmp_path)
    original.collection.add(
        ids=["existing"],
        embeddings=[_embedding(0.1)],
        documents=["existing document"],
        metadatas=[{"relative_path": "src/existing.py"}],
    )

    reopened = IndexStore.open_existing(
        tmp_path,
        embedding_function=FakeEmbeddingFunction(),
    )

    assert reopened.collection_count() == 1
    assert reopened.repo_path == tmp_path.resolve()


def test_open_existing_rejects_missing_repository_path(tmp_path):
    with pytest.raises(ValueError, match="existing directory"):
        IndexStore.open_existing(tmp_path / "missing")


def test_get_chunk_ids_for_file_filters_by_relative_path(tmp_path):
    store = IndexStore(tmp_path)
    store.collection.add(
        ids=["first", "second", "other"],
        embeddings=[_embedding(0.1), _embedding(0.2), _embedding(0.3)],
        documents=["first", "second", "other"],
        metadatas=[
            {"relative_path": "src/module.py"},
            {"relative_path": "src/module.py"},
            {"relative_path": "src/other.py"},
        ],
    )

    assert set(store.get_chunk_ids_for_file("src/module.py")) == {
        "first",
        "second",
    }
    assert store.get_chunk_ids_for_file("src/missing.py") == []


def test_upsert_chunks_adds_and_replaces_chunks(tmp_path):
    IndexStore(tmp_path)
    store = IndexStore.open_existing(
        tmp_path,
        embedding_function=FakeEmbeddingFunction(),
    )
    original = TextChunk(
        id="chunk-1",
        document="before",
        metadata={"relative_path": "src/module.py", "start_line": 1},
    )
    replacement = TextChunk(
        id="chunk-1",
        document="after",
        metadata={"relative_path": "src/module.py", "start_line": 2},
    )

    store.upsert_chunks([original])
    store.upsert_chunks([replacement])
    result = store.collection.get(ids=["chunk-1"])

    assert result["documents"] == ["after"]
    assert result["metadatas"] == [
        {"relative_path": "src/module.py", "start_line": 2}
    ]


def test_upsert_chunks_adds_multiple_chunks(tmp_path):
    IndexStore(tmp_path)
    store = IndexStore.open_existing(
        tmp_path,
        embedding_function=FakeEmbeddingFunction(),
    )
    chunks = [
        TextChunk(
            id=f"chunk-{index}",
            document=f"document {index}",
            metadata={"relative_path": "src/module.py", "chunk_index": index},
        )
        for index in range(3)
    ]

    store.upsert_chunks(chunks)
    result = store.collection.get(ids=[chunk.id for chunk in chunks])

    assert set(result["ids"]) == {"chunk-0", "chunk-1", "chunk-2"}
    assert result["documents"] is not None
    assert set(result["documents"]) == {
        "document 0",
        "document 1",
        "document 2",
    }


def test_upsert_chunks_with_empty_list_is_no_op():
    store = IndexStore.__new__(IndexStore)
    store._collection = Mock()

    store.upsert_chunks([])

    store._collection.upsert.assert_not_called()


def test_delete_chunks_by_ids_removes_selected_chunks(tmp_path):
    store = IndexStore(tmp_path)
    store.collection.add(
        ids=["keep", "remove"],
        embeddings=[_embedding(0.1), _embedding(0.2)],
        documents=["keep", "remove"],
        metadatas=[
            {"relative_path": "keep.py"},
            {"relative_path": "remove.py"},
        ],
    )

    store.delete_chunks_by_ids(["remove"])

    assert store.collection.get()["ids"] == ["keep"]


def test_delete_chunks_by_ids_with_empty_list_is_no_op():
    store = IndexStore.__new__(IndexStore)
    store._collection = Mock()

    store.delete_chunks_by_ids([])

    store._collection.delete.assert_not_called()


def test_delete_chunks_for_file_returns_count_and_removes_chunks(tmp_path):
    store = IndexStore(tmp_path)
    store.collection.add(
        ids=["first", "second", "keep"],
        embeddings=[_embedding(0.1), _embedding(0.2), _embedding(0.3)],
        documents=["first", "second", "keep"],
        metadatas=[
            {"relative_path": "src/remove.py"},
            {"relative_path": "src/remove.py"},
            {"relative_path": "src/keep.py"},
        ],
    )

    removed_count = store.delete_chunks_for_file("src/remove.py")

    assert removed_count == 2
    assert store.collection.get()["ids"] == ["keep"]


def test_delete_chunks_for_file_returns_zero_for_unknown_path(tmp_path):
    store = IndexStore(tmp_path)

    assert store.delete_chunks_for_file("src/missing.py") == 0


def test_index_store_public_surface():
    import codebase_indexer.index_store as index_store

    assert index_store.__all__ == [
        "IndexCorruptedError",
        "IndexNotInitializedError",
        "IndexStore",
    ]

import pytest

from codebase_indexer.config import (
    DEFAULT_COLLECTION_NAME,
    DEFAULT_INDEX_DIR_NAME,
    SKIP_DIRECTORIES,
)
from codebase_indexer.index_store import IndexStore


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
        embeddings=[[0.1, 0.2]],
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

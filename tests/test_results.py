import codebase_indexer.results as results
from codebase_indexer.results import (
    deleted_result,
    hash_failed_result,
    removed_unindexable_result,
    reindexed_result,
)


def test_reindexed_result_returns_plain_dict():
    result = reindexed_result("src/module.py", "a" * 64, 3, 1)

    assert type(result) is dict
    assert result == {
        "status": "reindexed",
        "relative_path": "src/module.py",
        "file_hash": "a" * 64,
        "chunks_added": 3,
        "chunks_removed": 1,
    }


def test_deleted_result_returns_plain_dict():
    result = deleted_result("src/deleted.py", 2)

    assert type(result) is dict
    assert result == {
        "status": "deleted",
        "relative_path": "src/deleted.py",
        "chunks_removed": 2,
    }


def test_removed_unindexable_result_returns_plain_dict():
    result = removed_unindexable_result("image.png", "unsupported", 1)

    assert type(result) is dict
    assert result == {
        "status": "removed_unindexable",
        "relative_path": "image.png",
        "reason": "unsupported",
        "chunks_removed": 1,
    }


def test_hash_failed_result_returns_retryable_plain_dict():
    result = hash_failed_result("src/module.py")

    assert type(result) is dict
    assert result == {
        "status": "hash_failed",
        "relative_path": "src/module.py",
        "retryable": True,
        "message": "File changed during hashing; retry after the write completes",
    }


def test_results_public_surface():
    assert results.__all__ == [
        "DeletedResult",
        "HashFailedResult",
        "RemovedUnindexableResult",
        "ReindexedResult",
        "ReindexResult",
        "deleted_result",
        "hash_failed_result",
        "removed_unindexable_result",
        "reindexed_result",
    ]


def test_result_statuses_are_unique_discriminators():
    results_by_status = {
        reindexed_result("module.py", "a" * 64, 1, 0)["status"],
        deleted_result("module.py", 0)["status"],
        removed_unindexable_result("module.py", "unsupported", 0)["status"],
        hash_failed_result("module.py")["status"],
    }

    assert results_by_status == {
        "reindexed",
        "deleted",
        "removed_unindexable",
        "hash_failed",
    }


def test_result_builders_allow_zero_chunk_counts():
    assert reindexed_result("empty.py", "a" * 64, 0, 0)["chunks_added"] == 0
    assert deleted_result("never-indexed.py", 0)["chunks_removed"] == 0

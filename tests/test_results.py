import codebase_indexer.results as results
from codebase_indexer.results import (
    deleted_result,
    file_not_found_result,
    hash_failed_result,
    index_status_result,
    initialized_result,
    partial_failure_result,
    not_indexable_result,
    reindexed_result,
    removed_index_result,
    search_match_result,
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


def test_file_not_found_result_returns_plain_dict():
    result = file_not_found_result("src/deleted.py")

    assert type(result) is dict
    assert result == {
        "status": "file_not_found",
        "relative_path": "src/deleted.py",
    }


def test_not_indexable_result_returns_plain_dict():
    result = not_indexable_result("image.png", "unsupported")

    assert type(result) is dict
    assert result == {
        "status": "not_indexable",
        "relative_path": "image.png",
        "reason": "unsupported",
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


def test_index_status_result_returns_clean_plain_dict():
    result = index_status_result(
        "/repo",
        "/repo/.codebase-index",
        "codebase_indexer",
        2,
        4,
        [],
        [],
        [],
    )

    assert type(result) is dict
    assert result == {
        "status": "clean",
        "repo_path": "/repo",
        "index_path": "/repo/.codebase-index",
        "collection_name": "codebase_indexer",
        "indexed_files": 2,
        "indexed_chunks": 4,
        "files_to_reindex": [],
        "files_to_delete": [],
        "files_with_errors": [],
    }


def test_index_status_result_reports_changes_when_errors_exist():
    result = index_status_result(
        "/repo",
        "/index",
        "collection",
        0,
        0,
        [],
        [],
        [{"relative_path": "module.py", "reason": "cannot read"}],
    )

    assert result["status"] == "changes_detected"


def test_removed_index_result_returns_plain_dict():
    result = removed_index_result("/repo", "/repo/.codebase-index")

    assert type(result) is dict
    assert result == {
        "status": "removed",
        "repo_path": "/repo",
        "index_path": "/repo/.codebase-index",
    }


def test_search_match_result_returns_plain_dict():
    result = search_match_result("src/module.py", 4, 12, stale=False)

    assert type(result) is dict
    assert result == {
        "relative_path": "src/module.py",
        "start_line": 4,
        "end_line": 12,
        "stale": False,
    }


def test_initialized_result_with_created_true_includes_walk_counts():
    result = initialized_result(
        "/repo",
        "/repo/.codebase-index",
        created=True,
        files_indexed=4,
        chunks_indexed=12,
        files_skipped=2,
    )

    assert type(result) is dict
    assert result == {
        "status": "initialized",
        "repo_path": "/repo",
        "index_path": "/repo/.codebase-index",
        "created": True,
        "files_indexed": 4,
        "chunks_indexed": 12,
        "files_skipped": 2,
    }


def test_initialized_result_with_created_false_omits_walk_counts():
    result = initialized_result(
        "/repo",
        "/repo/.codebase-index",
        created=False,
        files_indexed=4,
        chunks_indexed=12,
        files_skipped=2,
    )

    assert result == {
        "status": "initialized",
        "repo_path": "/repo",
        "index_path": "/repo/.codebase-index",
        "created": False,
    }


def test_partial_failure_result_returns_plain_dict():
    failures = [
        {"relative_path": "src/broken.py", "reason": "hash failed"},
        {"relative_path": "src/locked.py", "reason": "permission denied"},
    ]

    result = partial_failure_result(
        "/repo",
        "/repo/.codebase-index",
        files_indexed=3,
        chunks_indexed=8,
        files_skipped=1,
        failures=failures,
    )

    assert type(result) is dict
    assert result == {
        "status": "partial_failure",
        "repo_path": "/repo",
        "index_path": "/repo/.codebase-index",
        "files_indexed": 3,
        "chunks_indexed": 8,
        "files_skipped": 1,
        "files_failed": 2,
        "failures": failures,
    }


def test_results_public_surface():
    assert results.__all__ == [
        "DeletedResult",
        "FileNotFoundResult",
        "HashFailedResult",
        "InitializedResult",
        "IndexStatusAction",
        "IndexStatusError",
        "IndexStatusResult",
        "IndexRepoResult",
        "NotIndexableResult",
        "PartialFailureDetail",
        "PartialFailureResult",
        "ReindexedResult",
        "ReindexResult",
        "RemovedIndexResult",
        "SearchMatch",
        "deleted_result",
        "file_not_found_result",
        "hash_failed_result",
        "initialized_result",
        "index_status_result",
        "not_indexable_result",
        "partial_failure_result",
        "reindexed_result",
        "removed_index_result",
        "search_match_result",
    ]


def test_result_statuses_are_unique_discriminators():
    results_by_status = {
        reindexed_result("module.py", "a" * 64, 1, 0)["status"],
        deleted_result("module.py", 0)["status"],
        file_not_found_result("missing.py")["status"],
        not_indexable_result("module.py", "unsupported")["status"],
        hash_failed_result("module.py")["status"],
        initialized_result("/repo", "/index", created=False)["status"],
        index_status_result("/repo", "/index", "collection", 0, 0, [], [], [
            {"relative_path": "file.py", "reason": "error"}
        ])["status"],
        partial_failure_result("/repo", "/index", 0, 0, 0, [])["status"],
        removed_index_result("/repo", "/index")["status"],
    }

    assert results_by_status == {
        "reindexed",
        "deleted",
        "file_not_found",
        "not_indexable",
        "hash_failed",
        "initialized",
        "changes_detected",
        "partial_failure",
        "removed",
    }


def test_result_builders_allow_zero_chunk_counts():
    assert reindexed_result("empty.py", "a" * 64, 0, 0)["chunks_added"] == 0
    assert deleted_result("never-indexed.py", 0)["chunks_removed"] == 0

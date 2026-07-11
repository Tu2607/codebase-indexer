"""Plain dictionary result contracts for indexing and file reindexing."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

__all__ = [
    "DeletedResult",
    "HashFailedResult",
    "InitializedResult",
    "IndexRepoResult",
    "PartialFailureDetail",
    "PartialFailureResult",
    "RemovedUnindexableResult",
    "ReindexedResult",
    "ReindexResult",
    "deleted_result",
    "hash_failed_result",
    "initialized_result",
    "partial_failure_result",
    "removed_unindexable_result",
    "reindexed_result",
]


class InitializedResult(TypedDict):
    status: Literal["initialized"]
    repo_path: str
    index_path: str
    created: bool
    files_indexed: NotRequired[int]
    chunks_indexed: NotRequired[int]
    files_skipped: NotRequired[int]


class PartialFailureDetail(TypedDict):
    relative_path: str
    reason: str


class PartialFailureResult(TypedDict):
    status: Literal["partial_failure"]
    repo_path: str
    index_path: str
    files_indexed: int
    chunks_indexed: int
    files_skipped: int
    files_failed: int
    failures: list[PartialFailureDetail]


class ReindexedResult(TypedDict):
    status: Literal["reindexed"]
    relative_path: str
    file_hash: str
    chunks_added: int
    chunks_removed: int


class DeletedResult(TypedDict):
    status: Literal["deleted"]
    relative_path: str
    chunks_removed: int


class RemovedUnindexableResult(TypedDict):
    status: Literal["removed_unindexable"]
    relative_path: str
    reason: str
    chunks_removed: int


class HashFailedResult(TypedDict):
    status: Literal["hash_failed"]
    relative_path: str
    retryable: Literal[True]
    message: str


ReindexResult = (
    ReindexedResult
    | DeletedResult
    | RemovedUnindexableResult
    | HashFailedResult
)
IndexRepoResult = InitializedResult


def initialized_result(
    repo_path: str,
    index_path: str,
    *,
    created: bool,
    files_indexed: int = 0,
    chunks_indexed: int = 0,
    files_skipped: int = 0,
) -> InitializedResult:
    result: InitializedResult = {
        "status": "initialized",
        "repo_path": repo_path,
        "index_path": index_path,
        "created": created,
    }
    if created:
        result.update(
            files_indexed=files_indexed,
            chunks_indexed=chunks_indexed,
            files_skipped=files_skipped,
        )
    return result


def partial_failure_result(
    repo_path: str,
    index_path: str,
    files_indexed: int,
    chunks_indexed: int,
    files_skipped: int,
    failures: list[PartialFailureDetail],
) -> PartialFailureResult:
    return {
        "status": "partial_failure",
        "repo_path": repo_path,
        "index_path": index_path,
        "files_indexed": files_indexed,
        "chunks_indexed": chunks_indexed,
        "files_skipped": files_skipped,
        "files_failed": len(failures),
        "failures": failures,
    }


def reindexed_result(
    relative_path: str,
    file_hash: str,
    chunks_added: int,
    chunks_removed: int,
) -> ReindexedResult:
    return {
        "status": "reindexed",
        "relative_path": relative_path,
        "file_hash": file_hash,
        "chunks_added": chunks_added,
        "chunks_removed": chunks_removed,
    }


def deleted_result(relative_path: str, chunks_removed: int) -> DeletedResult:
    return {
        "status": "deleted",
        "relative_path": relative_path,
        "chunks_removed": chunks_removed,
    }


def removed_unindexable_result(
    relative_path: str,
    reason: str,
    chunks_removed: int,
) -> RemovedUnindexableResult:
    return {
        "status": "removed_unindexable",
        "relative_path": relative_path,
        "reason": reason,
        "chunks_removed": chunks_removed,
    }


def hash_failed_result(relative_path: str) -> HashFailedResult:
    return {
        "status": "hash_failed",
        "relative_path": relative_path,
        "retryable": True,
        "message": "File changed during hashing; retry after the write completes",
    }

"""Plain dictionary result contracts for indexing and file reindexing."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

__all__ = [
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
    "deleted_result",
    "file_not_found_result",
    "hash_failed_result",
    "initialized_result",
    "index_status_result",
    "not_indexable_result",
    "partial_failure_result",
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


class IndexStatusAction(TypedDict):
    relative_path: str
    reason: str


class IndexStatusError(TypedDict):
    relative_path: str
    reason: str


class IndexStatusResult(TypedDict):
    status: Literal["clean", "changes_detected"]
    repo_path: str
    index_path: str
    collection_name: str
    indexed_files: int
    indexed_chunks: int
    files_to_reindex: list[IndexStatusAction]
    files_to_delete: list[IndexStatusAction]
    files_with_errors: list[IndexStatusError]


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


class FileNotFoundResult(TypedDict):
    status: Literal["file_not_found"]
    relative_path: str


class NotIndexableResult(TypedDict):
    status: Literal["not_indexable"]
    relative_path: str
    reason: str


class HashFailedResult(TypedDict):
    status: Literal["hash_failed"]
    relative_path: str
    retryable: Literal[True]
    message: str


ReindexResult = (
    ReindexedResult
    | FileNotFoundResult
    | NotIndexableResult
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


def index_status_result(
    repo_path: str,
    index_path: str,
    collection_name: str,
    indexed_files: int,
    indexed_chunks: int,
    files_to_reindex: list[IndexStatusAction],
    files_to_delete: list[IndexStatusAction],
    files_with_errors: list[IndexStatusError],
) -> IndexStatusResult:
    has_changes = bool(files_to_reindex or files_to_delete or files_with_errors)
    return {
        "status": "changes_detected" if has_changes else "clean",
        "repo_path": repo_path,
        "index_path": index_path,
        "collection_name": collection_name,
        "indexed_files": indexed_files,
        "indexed_chunks": indexed_chunks,
        "files_to_reindex": files_to_reindex,
        "files_to_delete": files_to_delete,
        "files_with_errors": files_with_errors,
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


def file_not_found_result(relative_path: str) -> FileNotFoundResult:
    return {
        "status": "file_not_found",
        "relative_path": relative_path,
    }


def not_indexable_result(
    relative_path: str,
    reason: str,
) -> NotIndexableResult:
    return {
        "status": "not_indexable",
        "relative_path": relative_path,
        "reason": reason,
    }


def hash_failed_result(relative_path: str) -> HashFailedResult:
    return {
        "status": "hash_failed",
        "relative_path": relative_path,
        "retryable": True,
        "message": "File changed during hashing; retry after the write completes",
    }

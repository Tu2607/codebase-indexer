"""Initial repository indexing orchestration."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
from pathlib import Path

from . import config
from .chunker import TextChunk, chunk_by_lines
from .file_finder import iter_indexable_files
from .hashing import hash_file
from .index_store import IndexStore
from .results import (
    InitializedResult,
    PartialFailureDetail,
    initialized_result,
    partial_failure_result,
)

__all__ = ["index_repository"]


class IndexPartialFailureError(Exception):
    """Raised when some files fail during initial indexing."""


@dataclass(frozen=True)
class _PreparedFile:
    relative_path: str
    chunks: list[TextChunk]


@dataclass(frozen=True)
class _FileFailure:
    relative_path: str
    reason: str


def _prepare_file(
    file_path: Path,
    repo_path: Path,
    relative_path: str,
) -> _PreparedFile:
    """Hash and chunk one discovered file without accessing the index store."""

    file_hash = hash_file(file_path)
    chunks = chunk_by_lines(
        file_path,
        repo_path=repo_path,
        file_hash=file_hash,
    )
    return _PreparedFile(relative_path, chunks)


def index_repository(store: IndexStore, repo_path: Path) -> InitializedResult:
    """Prepare and index all eligible files in a newly created repository index."""

    resolved_repo_path = Path(repo_path).resolve()
    eligible_files, skipped_count = iter_indexable_files(resolved_repo_path)
    repo_path_string = str(resolved_repo_path)
    index_path_string = str(Path(store.index_dir).resolve())

    if not eligible_files:
        return initialized_result(
            repo_path_string,
            index_path_string,
            created=True,
            files_indexed=0,
            chunks_indexed=0,
            files_skipped=skipped_count,
        )

    files_indexed = 0
    chunks_indexed = 0
    failures: list[_FileFailure] = []

    with ThreadPoolExecutor(
        max_workers=config.DEFAULT_MAX_INDEX_WORKERS
    ) as executor:
        for batch_start in range(
            0,
            len(eligible_files),
            config.DEFAULT_INDEX_BATCH_SIZE,
        ):
            batch = eligible_files[
                batch_start : batch_start + config.DEFAULT_INDEX_BATCH_SIZE
            ]
            futures: dict[Future[_PreparedFile], str] = {
                executor.submit(
                    _prepare_file,
                    file_path,
                    resolved_repo_path,
                    relative_path,
                ): relative_path
                for file_path, relative_path in batch
            }

            for future in as_completed(futures):
                relative_path = futures[future]
                try:
                    prepared_file = future.result()
                except Exception as exc:
                    failures.append(_FileFailure(relative_path, str(exc)))
                    continue

                try:
                    store.upsert_chunks(prepared_file.chunks)
                except Exception as exc:
                    failures.append(
                        _FileFailure(
                            relative_path,
                            f"index write failed: {exc}",
                        )
                    )
                    continue

                files_indexed += 1
                chunks_indexed += len(prepared_file.chunks)

    if failures:
        failures.sort(key=lambda failure: failure.relative_path)
        failure_details: list[PartialFailureDetail] = [
            {
                "relative_path": failure.relative_path,
                "reason": failure.reason,
            }
            for failure in failures
        ]
        result = partial_failure_result(
            repo_path_string,
            index_path_string,
            files_indexed,
            chunks_indexed,
            skipped_count,
            failure_details,
        )
        raise IndexPartialFailureError(json.dumps(result))

    return initialized_result(
        repo_path_string,
        index_path_string,
        created=True,
        files_indexed=files_indexed,
        chunks_indexed=chunks_indexed,
        files_skipped=skipped_count,
    )

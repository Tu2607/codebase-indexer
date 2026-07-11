"""Single-file reindex orchestration."""

from __future__ import annotations

import os

from .chunker import chunk_by_lines
from .file_finder import should_index_file
from .hashing import FileChangedDuringHashingError, hash_file
from .index_store import IndexStore
from .path_utils import resolve_repo_file_path
from .results import (
    DeletedResult,
    ReindexResult,
    deleted_result,
    hash_failed_result,
    removed_unindexable_result,
    reindexed_result,
)

__all__ = ["reindex_single_file"]


def reindex_single_file(
    store: IndexStore,
    file_path: str,
    repo_path: str | os.PathLike[str],
) -> ReindexResult:
    """Reindex one file, preserving old chunks until replacement succeeds.

    Chunk replacement is not atomic: a deletion failure after an upsert can leave
    old and new chunks together. Retrying the same file reindex removes the stale
    IDs and restores the expected state.
    """

    resolved_repo_path, resolved_file_path, relative_path = resolve_repo_file_path(
        repo_path,
        file_path,
    )

    if not resolved_file_path.exists():
        return _deleted_result(store, relative_path)

    try:
        is_indexable, reason = should_index_file(
            resolved_file_path,
            resolved_repo_path,
        )
        if not is_indexable:
            chunks_removed = store.delete_chunks_for_file(relative_path)
            return removed_unindexable_result(
                relative_path,
                reason or "not indexable",
                chunks_removed,
            )

        file_hash = hash_file(resolved_file_path)
        chunks = chunk_by_lines(
            resolved_file_path,
            repo_path=resolved_repo_path,
            file_hash=file_hash,
        )
    except FileNotFoundError:
        return _deleted_result(store, relative_path)
    except FileChangedDuringHashingError:
        return hash_failed_result(relative_path)

    old_ids = store.get_chunk_ids_for_file(relative_path)
    store.upsert_chunks(chunks)

    new_ids = {chunk.id for chunk in chunks}
    chunks_added = len(new_ids.difference(old_ids))
    stale_ids = [chunk_id for chunk_id in old_ids if chunk_id not in new_ids]
    store.delete_chunks_by_ids(stale_ids)

    return reindexed_result(
        relative_path,
        file_hash,
        chunks_added,
        len(stale_ids),
    )


def _deleted_result(store: IndexStore, relative_path: str) -> DeletedResult:
    chunks_removed = store.delete_chunks_for_file(relative_path)
    return deleted_result(relative_path, chunks_removed)

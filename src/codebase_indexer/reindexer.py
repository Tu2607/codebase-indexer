"""Single-file reindex orchestration."""

from __future__ import annotations

import os

from .chunker import chunk_by_lines
from .file_finder import should_index_file
from .hashing import FileChangedDuringHashingError, hash_file
from .index_store import IndexStore
from .path_utils import resolve_repo_file_path
from .results import (
    ReindexResult,
    file_not_found_result,
    hash_failed_result,
    not_indexable_result,
    reindexed_result,
)

__all__ = ["reindex_single_file"]


def reindex_single_file(
    store: IndexStore,
    file_path: str,
    repo_path: str | os.PathLike[str],
) -> ReindexResult:
    """Reindex an existing indexable file.

    Missing and unindexable files are reported without changing stored chunks.
    Successful replacement is not atomic: a stale-ID deletion failure after an
    upsert can leave old and new chunks together. Retrying removes the stale IDs.
    """

    resolved_repo_path, resolved_file_path, relative_path = resolve_repo_file_path(
        repo_path,
        file_path,
    )

    if not resolved_file_path.exists():
        return file_not_found_result(relative_path)

    try:
        is_indexable, reason = should_index_file(
            resolved_file_path,
            resolved_repo_path,
        )
        if not is_indexable:
            return not_indexable_result(
                relative_path,
                reason or "not indexable",
            )

        file_hash = hash_file(resolved_file_path)
        chunks = chunk_by_lines(
            resolved_file_path,
            repo_path=resolved_repo_path,
            file_hash=file_hash,
        )
    except FileNotFoundError:
        return file_not_found_result(relative_path)
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

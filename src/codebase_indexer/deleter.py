"""Explicit single-file index deletion orchestration."""

from __future__ import annotations

import os

from .index_store import IndexStore
from .path_utils import resolve_repo_file_path
from .results import DeletedResult, deleted_result

__all__ = ["delete_indexed_file"]


def delete_indexed_file(
    store: IndexStore,
    file_path: str,
    repo_path: str | os.PathLike[str],
) -> DeletedResult:
    """Delete every indexed chunk for one normalized repository path."""

    _, _, relative_path = resolve_repo_file_path(repo_path, file_path)
    chunks_removed = store.delete_chunks_for_file(relative_path)
    return deleted_result(relative_path, chunks_removed)

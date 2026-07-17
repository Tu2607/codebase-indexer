"""Read-only comparison of repository files and indexed chunk metadata."""

from __future__ import annotations

import os
from pathlib import Path

from .config import DEFAULT_COLLECTION_NAME
from .file_finder import iter_indexable_files, should_index_file
from .hashing import FileChangedDuringHashingError, hash_file
from .index_store import IndexStore
from .path_utils import resolve_repo_file_path
from .results import (
    IndexStatusAction,
    IndexStatusError,
    IndexStatusResult,
    index_status_result,
)

__all__ = ["get_repository_index_status"]


def get_repository_index_status(
    store: IndexStore,
    repo_path: str | os.PathLike[str],
) -> IndexStatusResult:
    """Report repository/index drift without changing either source."""

    resolved_repo_path = Path(repo_path).resolve()
    metadata = store.get_indexed_file_metadata()
    indexed_hashes, files_with_errors = _group_indexed_hashes(metadata)
    indexed_paths = set(indexed_hashes)
    errored_paths = {
        item["relative_path"]
        for item in files_with_errors
        if not item["relative_path"].startswith("<metadata:")
    }

    discovered_files, _ = iter_indexable_files(resolved_repo_path)
    eligible_files = {
        relative_path: file_path for file_path, relative_path in discovered_files
    }

    files_to_reindex: list[IndexStatusAction] = []
    files_to_delete: list[IndexStatusAction] = []

    for relative_path in sorted(indexed_paths):
        try:
            _, file_path, normalized_path = resolve_repo_file_path(
                resolved_repo_path,
                relative_path,
            )
        except ValueError as exc:
            files_with_errors.append(_error(relative_path, str(exc)))
            continue

        if normalized_path != relative_path:
            files_with_errors.append(
                _error(relative_path, "indexed relative path is not normalized")
            )
            continue

        if not file_path.exists():
            files_to_delete.append(_action(relative_path, "missing"))
            continue

        try:
            is_indexable, _ = should_index_file(file_path, resolved_repo_path)
        except FileNotFoundError:
            files_to_delete.append(_action(relative_path, "missing"))
            continue
        except OSError as exc:
            files_with_errors.append(_error(relative_path, str(exc)))
            continue

        if not is_indexable:
            files_to_delete.append(
                _action(relative_path, "no_longer_indexable")
            )
            continue

        try:
            current_hash = hash_file(file_path)
        except FileNotFoundError:
            files_to_delete.append(_action(relative_path, "missing"))
            continue
        except FileChangedDuringHashingError as exc:
            files_with_errors.append(_error(relative_path, str(exc)))
            continue
        except OSError as exc:
            files_with_errors.append(_error(relative_path, str(exc)))
            continue

        stored_hashes = indexed_hashes[relative_path]
        if len(stored_hashes) != 1:
            files_to_reindex.append(_action(relative_path, "inconsistent_index"))
        elif current_hash not in stored_hashes:
            files_to_reindex.append(_action(relative_path, "content_changed"))

    known_paths = indexed_paths.union(errored_paths)
    for relative_path in sorted(set(eligible_files).difference(known_paths)):
        files_to_reindex.append(_action(relative_path, "not_indexed"))

    files_to_reindex.sort(key=lambda item: item["relative_path"])
    files_to_delete.sort(key=lambda item: item["relative_path"])
    files_with_errors.sort(key=lambda item: item["relative_path"])

    return index_status_result(
        str(resolved_repo_path),
        str(store.index_dir),
        DEFAULT_COLLECTION_NAME,
        len(indexed_paths),
        store.collection_count(),
        files_to_reindex,
        files_to_delete,
        files_with_errors,
    )


def _group_indexed_hashes(
    metadata_records: list[dict[str, object] | None],
) -> tuple[dict[str, set[str]], list[IndexStatusError]]:
    indexed_hashes: dict[str, set[str]] = {}
    errors: list[IndexStatusError] = []
    invalid_paths: set[str] = set()

    for index, metadata in enumerate(metadata_records):
        if not isinstance(metadata, dict):
            errors.append(_error(f"<metadata:{index}>", "missing chunk metadata"))
            continue

        relative_path = metadata.get("relative_path")
        if not isinstance(relative_path, str) or not relative_path:
            errors.append(
                _error(f"<metadata:{index}>", "missing indexed relative_path")
            )
            continue

        file_hash = metadata.get("file_hash")
        if not isinstance(file_hash, str) or not file_hash:
            errors.append(_error(relative_path, "missing indexed file_hash"))
            invalid_paths.add(relative_path)
            continue

        indexed_hashes.setdefault(relative_path, set()).add(file_hash)

    for relative_path in invalid_paths:
        indexed_hashes.pop(relative_path, None)

    return indexed_hashes, errors


def _action(relative_path: str, reason: str) -> IndexStatusAction:
    return {"relative_path": relative_path, "reason": reason}


def _error(relative_path: str, reason: str) -> IndexStatusError:
    return {"relative_path": relative_path, "reason": reason}

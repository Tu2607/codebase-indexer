"""Read-only semantic search orchestration for indexed repository chunks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .hashing import hash_file
from .index_store import IndexStore
from .path_utils import resolve_repo_file_path
from .results import SearchMatch, search_match_result

__all__ = ["SearchMetadataError", "search_repository"]


class SearchMetadataError(ValueError):
    """Raised when indexed chunk metadata cannot produce a safe source pointer."""


@dataclass(frozen=True)
class _SearchCandidate:
    relative_path: str
    file_path: Path
    start_line: int
    end_line: int
    file_hash: str


def search_repository(
    store: IndexStore,
    repo_path: Path,
    query: str,
    max_results: int,
    include_stale: bool,
) -> list[SearchMatch]:
    """Return ordered source pointers for the nearest indexed chunks."""

    metadata = store.query_chunks(query, max_results)
    candidates = [
        _validate_candidate(item, index, repo_path)
        for index, item in enumerate(metadata)
    ]

    current_hashes: dict[str, str | None] = {}
    matches: list[SearchMatch] = []
    for candidate in candidates:
        if candidate.relative_path not in current_hashes:
            try:
                current_hashes[candidate.relative_path] = hash_file(
                    candidate.file_path
                )
            except OSError:
                current_hashes[candidate.relative_path] = None

        stale = current_hashes[candidate.relative_path] != candidate.file_hash
        if stale and not include_stale:
            continue

        matches.append(
            search_match_result(
                candidate.relative_path,
                candidate.start_line,
                candidate.end_line,
                stale=stale,
            )
        )

    return matches


def _validate_candidate(
    metadata: dict[str, object] | None,
    index: int,
    repo_path: Path,
) -> _SearchCandidate:
    label = f"Search result metadata at index {index}"
    if not isinstance(metadata, dict):
        raise SearchMetadataError(f"{label} is missing or invalid.")

    relative_path = metadata.get("relative_path")
    if not isinstance(relative_path, str) or not relative_path:
        raise SearchMetadataError(f"{label} has invalid relative_path.")

    file_hash = metadata.get("file_hash")
    if not isinstance(file_hash, str) or not file_hash:
        raise SearchMetadataError(f"{label} has invalid file_hash.")

    start_line = metadata.get("start_line")
    end_line = metadata.get("end_line")
    if type(start_line) is not int or start_line < 1:
        raise SearchMetadataError(f"{label} has invalid start_line.")
    if type(end_line) is not int or end_line < start_line:
        raise SearchMetadataError(f"{label} has invalid end_line.")

    try:
        _, file_path, normalized_relative_path = resolve_repo_file_path(
            repo_path,
            relative_path,
        )
    except ValueError as exc:
        raise SearchMetadataError(f"{label} has invalid relative_path: {exc}") from exc

    if normalized_relative_path != relative_path:
        raise SearchMetadataError(
            f"{label} has a non-normalized relative_path: {relative_path}"
        )

    return _SearchCandidate(
        relative_path=relative_path,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        file_hash=file_hash,
    )

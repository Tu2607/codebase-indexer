"""Line-based source file chunking helpers."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .config import DEFAULT_CHUNK_OVERLAP_LINES, DEFAULT_CHUNK_SIZE_LINES
from .repo_id import repo_path_hash

__all__ = ["TextChunk", "chunk_by_lines"] # Exported for use in other modules


@dataclass(frozen=True)
class TextChunk:
    """A text segment ready for storage in the repository index."""

    id: str
    document: str
    metadata: dict[str, str | int]


def chunk_by_lines(
    file_path: str | os.PathLike[str],
    *,
    repo_path: str | os.PathLike[str],
    file_hash: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE_LINES,
    overlap: int = DEFAULT_CHUNK_OVERLAP_LINES,
) -> list[TextChunk]:
    """Split a repository file into overlapping, line-based text chunks."""

    _validate_chunk_settings(chunk_size, overlap)

    resolved_repo_path = Path(repo_path).resolve()
    resolved_file_path = Path(file_path).resolve()

    try:
        relative_path = resolved_file_path.relative_to(resolved_repo_path).as_posix()
    except ValueError:
        raise ValueError("file_path is not inside repo_path") from None

    with resolved_file_path.open(
        encoding="utf-8", errors="replace", newline=""
    ) as file_obj:
        lines = file_obj.read().splitlines(keepends=True)
    if not lines:
        return []

    step = chunk_size - overlap
    chunks = []
    start = 0
    chunk_index = 0

    while start < len(lines):
        chunk_lines = lines[start : start + chunk_size]
        chunks.append(
            TextChunk(
                id=_chunk_id(
                    repo_path_hash(resolved_repo_path),
                    relative_path,
                    chunk_index,
                    file_hash,
                ),
                document="".join(chunk_lines),
                metadata={
                    "repo_path": str(resolved_repo_path),
                    "file_path": str(resolved_file_path),
                    "relative_path": relative_path,
                    "start_line": start + 1,
                    "end_line": start + len(chunk_lines),
                    "file_hash": file_hash,
                    "chunk_index": chunk_index,
                },
            )
        )

        if start + chunk_size >= len(lines):
            break

        start += step
        chunk_index += 1

    return chunks


def _validate_chunk_settings(chunk_size: int, overlap: int) -> None:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= chunk_size:
        raise ValueError("overlap must be less than chunk_size")


def _chunk_id(
    repo_hash: str,
    relative_path: str,
    chunk_index: int,
    file_hash: str,
) -> str:
    return f"{repo_hash}:{relative_path}:{chunk_index}:{file_hash[:12]}"

"""Single-file index eligibility checks."""

from __future__ import annotations

import stat
from pathlib import Path

from codebase_indexer.config import (
    INDEX_EXTENSIONS,
    INDEX_FILENAMES,
    MAX_FILE_SIZE_BYTES,
    SKIP_DIRECTORIES,
)

__all__ = ["should_index_file"]


def should_index_file(file_path: Path, repo_path: Path) -> tuple[bool, str | None]:
    """Return whether an existing file is eligible for indexing and why not."""

    file_stat = file_path.stat()

    if not stat.S_ISREG(file_stat.st_mode):
        return False, "not a regular file"

    relative_path = file_path.relative_to(repo_path)

    for component in relative_path.parts[:-1]:
        if component in SKIP_DIRECTORIES:
            return False, f"inside skipped directory: {component}"

    if file_path.suffix not in INDEX_EXTENSIONS and file_path.name not in INDEX_FILENAMES:
        return False, f"unsupported file type: {file_path.name}"

    if file_stat.st_size > MAX_FILE_SIZE_BYTES:
        return (
            False,
            f"file too large: {file_stat.st_size} bytes, "
            f"limit {MAX_FILE_SIZE_BYTES} bytes",
        )

    return True, None

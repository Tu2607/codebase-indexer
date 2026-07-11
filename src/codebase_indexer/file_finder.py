"""Repository file discovery and index eligibility checks."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from codebase_indexer.config import (
    INDEX_EXTENSIONS,
    INDEX_FILENAMES,
    MAX_FILE_SIZE_BYTES,
    SKIP_DIRECTORIES,
)

__all__ = ["iter_indexable_files", "should_index_file"]


def iter_indexable_files(repo_path: Path) -> tuple[list[tuple[Path, str]], int]:
    """Discover indexable repository files and return them in stable order."""

    canonical_repo_path = repo_path.resolve()
    eligible_files: list[tuple[Path, str]] = []
    seen_canonical: set[Path] = set()
    skipped_count = 0

    for dirpath, dirnames, filenames in os.walk(repo_path, followlinks=False):
        dirnames[:] = sorted(
            directory
            for directory in dirnames
            if directory not in SKIP_DIRECTORIES
        )

        for filename in sorted(filenames):
            file_path = Path(dirpath) / filename

            try:
                is_indexable, _ = should_index_file(file_path, repo_path)
                if not is_indexable:
                    skipped_count += 1
                    continue

                canonical_path = file_path.resolve()
                relative_path = canonical_path.relative_to(
                    canonical_repo_path
                ).as_posix()
            except OSError:
                skipped_count += 1
                continue
            except ValueError:
                skipped_count += 1
                continue

            if any(
                component in SKIP_DIRECTORIES
                for component in Path(relative_path).parts[:-1]
            ):
                skipped_count += 1
                continue

            if canonical_path in seen_canonical:
                skipped_count += 1
                continue

            seen_canonical.add(canonical_path)
            eligible_files.append((canonical_path, relative_path))

    eligible_files.sort(key=lambda discovered: discovered[1])
    return eligible_files, skipped_count


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

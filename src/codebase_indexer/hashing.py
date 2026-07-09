"""SHA-256 file hashing helpers."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

__all__ = ["hash_file", "FileChangedDuringHashingError"]

_READ_BUFFER_SIZE = 64 * 1024


class FileChangedDuringHashingError(OSError):
    """Raised when file metadata changes while a hash is being computed."""


def hash_file(path: str | os.PathLike[str]) -> str:
    """Return the SHA-256 hex digest for a regular file's raw bytes."""

    file_path = Path(path)
    _require_regular_file(file_path)

    before = _stat_for_consistency(file_path)
    digest = hashlib.sha256()

    with file_path.open("rb") as file_obj:
        while chunk := file_obj.read(_READ_BUFFER_SIZE):
            digest.update(chunk)

    after = _stat_for_consistency(file_path)
    _raise_if_file_changed(file_path, before, after)

    return digest.hexdigest()


def _require_regular_file(path: Path) -> None:
    try:
        path_stat = path.stat()
    except FileNotFoundError:
        if path.is_symlink():
            raise OSError(f"Path is not a regular file: {path}") from None
        raise

    if stat.S_ISDIR(path_stat.st_mode):
        raise IsADirectoryError(path)

    if not stat.S_ISREG(path_stat.st_mode):
        raise OSError(f"Path is not a regular file: {path}")


def _stat_for_consistency(path: Path) -> os.stat_result:
    # Kept as a tiny wrapper so tests can simulate metadata changing mid-read.
    return path.stat()


def _raise_if_file_changed(
    path: Path,
    before: os.stat_result,
    after: os.stat_result,
) -> None:
    changed_fields = []

    if before.st_size != after.st_size:
        changed_fields.append("st_size")

    if before.st_mtime_ns != after.st_mtime_ns:
        changed_fields.append("st_mtime_ns")

    if changed_fields:
        joined_fields = ", ".join(changed_fields)
        raise FileChangedDuringHashingError(
            f"File changed during hashing: {path} ({joined_fields})"
        )

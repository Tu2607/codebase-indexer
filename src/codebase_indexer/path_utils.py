"""Repository-scoped path normalization helpers."""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["resolve_repo_file_path", "validate_repo_path"]


def validate_repo_path(repo_path: str | os.PathLike[str] | None) -> Path:
    """Return a resolved existing repository directory."""

    if repo_path is None:
        normalized_repo_path = ""
    elif isinstance(repo_path, str):
        normalized_repo_path = repo_path.strip()
    else:
        normalized_repo_path = os.fspath(repo_path).strip()

    if not normalized_repo_path:
        raise ValueError("repo_path is required.")

    resolved_repo_path = Path(normalized_repo_path).resolve()
    if not resolved_repo_path.is_dir():
        raise ValueError(
            f"repo_path must be an existing directory: {resolved_repo_path}"
        )

    return resolved_repo_path


def resolve_repo_file_path(
    repo_path: str | os.PathLike[str],
    file_path: str | os.PathLike[str],
) -> tuple[Path, Path, str]:
    """Resolve a file path inside a repository and return its POSIX relative path."""

    resolved_repo_path = validate_repo_path(repo_path)

    candidate_file_path = Path(file_path)
    if not candidate_file_path.is_absolute():
        candidate_file_path = resolved_repo_path / candidate_file_path

    resolved_file_path = candidate_file_path.resolve()

    try:
        relative_path = resolved_file_path.relative_to(resolved_repo_path).as_posix()
    except ValueError:
        raise ValueError(
            f"file_path {resolved_file_path} resolves outside repo_path "
            f"{resolved_repo_path}"
        ) from None

    if relative_path == ".":
        raise ValueError("file_path must not resolve to the repository root")

    return resolved_repo_path, resolved_file_path, relative_path

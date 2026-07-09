"""Stable identifiers derived from repository paths."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

__all__ = ["repo_path_hash"]

_REPO_HASH_LENGTH = 12


def repo_path_hash(path: str | os.PathLike[str]) -> str:
    """Return a stable short SHA-256 identifier for a resolved repository path."""

    resolved_path = Path(path).resolve()
    digest = hashlib.sha256(str(resolved_path).encode("utf-8"))
    return digest.hexdigest()[:_REPO_HASH_LENGTH]

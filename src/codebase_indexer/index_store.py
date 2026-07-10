"""Persistent ChromaDB collection lifecycle for one repository."""

from __future__ import annotations

import os
from pathlib import Path

import chromadb
from chromadb.api.models.Collection import Collection

from .config import DEFAULT_COLLECTION_NAME, DEFAULT_INDEX_DIR_NAME

__all__ = ["IndexStore"]


class IndexStore:
    """Open the persistent ChromaDB collection for a repository."""

    def __init__(self, repo_path: str | os.PathLike[str]) -> None:
        resolved_repo_path = Path(repo_path).resolve()
        if not resolved_repo_path.is_dir():
            raise ValueError(
                f"repo_path must be an existing directory: {resolved_repo_path}"
            )

        self._repo_path = resolved_repo_path
        self._index_dir = self._repo_path / DEFAULT_INDEX_DIR_NAME
        self._client = chromadb.PersistentClient(path=str(self._index_dir))
        self._collection = self._client.get_or_create_collection(
            name=DEFAULT_COLLECTION_NAME
        )

    @property
    def repo_path(self) -> Path:
        """Return the resolved repository path."""

        return self._repo_path

    @property
    def index_dir(self) -> Path:
        """Return the repository-local ChromaDB persistence directory."""

        return self._index_dir

    @property
    def collection(self) -> Collection:
        """Return the ChromaDB collection for future store operations."""

        return self._collection

    def collection_count(self) -> int:
        """Return the number of records in the collection."""

        return self._collection.count()

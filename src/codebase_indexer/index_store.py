"""Persistent ChromaDB collection lifecycle for one repository."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.api.types import Documents, EmbeddingFunction
from chromadb.errors import InternalError, NotFoundError

from .chunker import TextChunk
from .config import DEFAULT_COLLECTION_NAME, DEFAULT_INDEX_DIR_NAME

__all__ = ["IndexCorruptedError", "IndexNotInitializedError", "IndexStore"]

_CHROMA_DATABASE_FILENAME = "chroma.sqlite3"


class IndexCorruptedError(ValueError):
    """Raised when an existing repository index cannot be opened."""


class IndexNotInitializedError(ValueError):
    """Raised when a repository does not have an existing index collection."""


class IndexStore:
    """Open the persistent ChromaDB collection for a repository."""

    def __init__(self, repo_path: str | os.PathLike[str]) -> None:
        resolved_repo_path = _resolve_repo_path(repo_path)

        self._repo_path = resolved_repo_path
        self._index_dir = self._repo_path / DEFAULT_INDEX_DIR_NAME
        self._client = chromadb.PersistentClient(path=str(self._index_dir))
        self._collection = self._client.get_or_create_collection(
            name=DEFAULT_COLLECTION_NAME
        )

    @staticmethod
    def is_initialized(repo_path: str | os.PathLike[str]) -> bool:
        """Return whether the repository-local Chroma database exists."""

        index_dir = Path(repo_path).resolve() / DEFAULT_INDEX_DIR_NAME
        return _has_chroma_database(index_dir)

    @classmethod
    def open_existing(
        cls,
        repo_path: str | os.PathLike[str],
        *,
        embedding_function: EmbeddingFunction[Documents] | None = None,
    ) -> IndexStore:
        """Open an existing index without creating its directory or collection."""

        resolved_repo_path = _resolve_repo_path(repo_path)
        index_dir = resolved_repo_path / DEFAULT_INDEX_DIR_NAME

        if not _has_chroma_database(index_dir):
            raise IndexNotInitializedError(
                f"Repository index is not initialized; run index_repo first: "
                f"{resolved_repo_path}"
            )

        try:
            client = chromadb.PersistentClient(path=str(index_dir))
        except (InternalError, sqlite3.DatabaseError) as exc:
            raise IndexCorruptedError(
                f"Index database exists but cannot be opened ({exc}); remove .codebase-index "
                "and run index_repo until rebuild_index is available: "
                f"{resolved_repo_path}"
            ) from exc

        try:
            if embedding_function is None:
                collection = client.get_collection(name=DEFAULT_COLLECTION_NAME)
            else:
                collection = client.get_collection(
                    name=DEFAULT_COLLECTION_NAME,
                    embedding_function=embedding_function,
                )
        except NotFoundError as exc:
            raise IndexCorruptedError(
                f"Index database exists but collection is missing ({exc}); remove .codebase-index "
                "and run index_repo until rebuild_index is available: "
                f"{resolved_repo_path}"
            ) from exc

        store = cls.__new__(cls)
        store._repo_path = resolved_repo_path
        store._index_dir = index_dir
        store._client = client
        store._collection = collection
        return store

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

    def get_chunk_ids_for_file(self, relative_path: str) -> list[str]:
        """Return IDs for chunks indexed under one repository-relative path."""

        result = self._collection.get(
            where={"relative_path": relative_path},
            include=[],
        )
        return result["ids"]

    def get_indexed_file_metadata(self) -> list[dict[str, object] | None]:
        """Return chunk metadata used to build a read-only file status view."""

        result = self._collection.get(include=["metadatas"])
        return result["metadatas"] or []

    def upsert_chunks(self, chunks: list[TextChunk]) -> None:
        """Add or replace a collection of text chunks by ID."""

        if not chunks:
            return

        self._collection.upsert(
            ids=[chunk.id for chunk in chunks],
            documents=[chunk.document for chunk in chunks],
            metadatas=[chunk.metadata for chunk in chunks],
        )

    def delete_chunks_by_ids(self, ids: list[str]) -> None:
        """Delete chunks by ID."""

        if not ids:
            return

        self._collection.delete(ids=ids)

    def delete_chunks_for_file(self, relative_path: str) -> int:
        """Delete all chunks for one file and return the previous chunk count."""

        ids = self.get_chunk_ids_for_file(relative_path)
        self.delete_chunks_by_ids(ids)
        return len(ids)


def _resolve_repo_path(repo_path: str | os.PathLike[str]) -> Path:
    resolved_repo_path = Path(repo_path).resolve()
    if not resolved_repo_path.is_dir():
        raise ValueError(
            f"repo_path must be an existing directory: {resolved_repo_path}"
        )
    return resolved_repo_path


def _has_chroma_database(index_dir: Path) -> bool:
    return (index_dir / _CHROMA_DATABASE_FILENAME).is_file()

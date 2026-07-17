from typing import NoReturn

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from .config import SERVER_NAME
from .deleter import delete_indexed_file
from .indexer import IndexPartialFailureError, index_repository
from .index_store import IndexCorruptedError, IndexNotInitializedError, IndexStore
from .path_utils import validate_repo_path
from .reindexer import reindex_single_file
from .results import initialized_result
from .status import get_repository_index_status

mcp = FastMCP(SERVER_NAME)


def _raise_not_implemented(tool_name: str) -> NoReturn:
    raise ToolError(f"{tool_name} is scaffolded but not implemented yet.")


@mcp.tool(
    description=(
        "Initialize a repository index. Call this at the beginning of a "
        "session or when no usable index exists. If the index already exists "
        "and is healthy, returns immediately without modifying it. For "
        "updating individual files after edits, use reindex_file instead."
    )
)
def index_repo(repo_path: str) -> dict[str, object]:
    try:
        resolved_repo_path = validate_repo_path(repo_path)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    try:
        store = IndexStore.open_existing(resolved_repo_path)
    except IndexNotInitializedError:
        try:
            store = IndexStore(resolved_repo_path)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
    except IndexCorruptedError as exc:
        raise ToolError(str(exc)) from exc
    else:
        return initialized_result(
            str(resolved_repo_path),
            str(store.index_dir),
            created=False,
        )

    try:
        return index_repository(store, resolved_repo_path)
    except IndexPartialFailureError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(
    description=(
        "Re-index one existing, indexable file after it has been created, edited, "
        "or overwritten. Missing and unindexable files are reported without "
        "changing the index; use delete_file_from_index for deleted paths, old "
        "rename paths, and files that are no longer indexable. Requires an "
        "existing index created by index_repo."
    )
)
def reindex_file(repo_path: str, file_path: str) -> dict[str, object]:
    try:
        resolved_repo_path = validate_repo_path(repo_path)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    cleaned_file_path = file_path.strip() if file_path else ""
    if not cleaned_file_path:
        raise ToolError("file_path is required.")

    try:
        store = IndexStore.open_existing(resolved_repo_path)
    # Keep the specific MCP-facing error visible even though it subclasses ValueError.
    except IndexNotInitializedError as exc:
        raise ToolError(str(exc)) from exc
    except IndexCorruptedError as exc:
        raise ToolError(str(exc)) from exc
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    try:
        return reindex_single_file(store, cleaned_file_path, store.repo_path)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(
    description=(
        "Explicitly remove one path's chunks from an existing index, whether or "
        "not the file still exists. Use this for deleted files, files that are no "
        "longer indexable, and the old path of a rename; then reindex the new "
        "rename path separately."
    )
)
def delete_file_from_index(repo_path: str, file_path: str) -> dict[str, object]:
    try:
        resolved_repo_path = validate_repo_path(repo_path)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    cleaned_file_path = file_path.strip() if file_path else ""
    if not cleaned_file_path:
        raise ToolError("file_path is required.")

    try:
        store = IndexStore.open_existing(resolved_repo_path)
    except IndexNotInitializedError as exc:
        raise ToolError(str(exc)) from exc
    except IndexCorruptedError as exc:
        raise ToolError(str(exc)) from exc
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    try:
        return delete_indexed_file(store, cleaned_file_path, store.repo_path)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(
    description=(
        "Search indexed repository chunks to discover likely relevant files "
        "and code regions. Search results are discovery hints, not complete "
        "editing context; read target files directly before modifying them. "
        "After modifying any indexed file, call reindex_file for that file."
    )
)
def search_repo_context(
    repo_path: str,
    query: str,
    max_results: int = 5,
    include_stale: bool = False,
) -> list[dict[str, object]]:
    _raise_not_implemented("search_repo_context")


@mcp.tool(
    description=(
        "Read repository and index state, then report paths that need "
        "reindex_file or delete_file_from_index. This tool is read-only and "
        "never applies the reported actions."
    )
)
def get_index_status(repo_path: str) -> dict[str, object]:
    try:
        resolved_repo_path = validate_repo_path(repo_path)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    try:
        store = IndexStore.open_existing(resolved_repo_path)
    except IndexNotInitializedError as exc:
        raise ToolError(str(exc)) from exc
    except IndexCorruptedError as exc:
        raise ToolError(str(exc)) from exc
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    return get_repository_index_status(store, store.repo_path)

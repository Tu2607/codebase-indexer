from typing import NoReturn

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from .config import SERVER_NAME
from .index_store import IndexCorruptedError, IndexNotInitializedError, IndexStore
from .path_utils import validate_repo_path
from .reindexer import reindex_single_file

mcp = FastMCP(SERVER_NAME)


def _raise_not_implemented(tool_name: str) -> NoReturn:
    raise ToolError(f"{tool_name} is scaffolded but not implemented yet.")


@mcp.tool(
    description=(
        "Index important files in a repository. Use full repo indexing for "
        "initial setup, large pulled changes, or explicit user requests."
    )
)
def index_repo(repo_path: str, force: bool = False) -> dict[str, object]:
    _raise_not_implemented("index_repo")


@mcp.tool(
    description=(
        "Re-index one file after it has been edited, created, or overwritten. "
        "Call this after editing any indexed file. If the file was deleted, its "
        "chunks are removed from the index. Requires an existing index created "
        "by index_repo."
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
        "Remove one file's chunks from the index. Use this after deleting or "
        "renaming an indexed file."
    )
)
def delete_file_from_index(repo_path: str, file_path: str) -> dict[str, object]:
    _raise_not_implemented("delete_file_from_index")


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


@mcp.tool(description="Return debugging information about the current index.")
def get_index_status(repo_path: str | None = None) -> dict[str, object]:
    _raise_not_implemented("get_index_status")

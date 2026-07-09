from typing import NoReturn

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from .config import SERVER_NAME

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
        "Agents should call this after editing an indexed file."
    )
)
def reindex_file(file_path: str) -> dict[str, object]:
    _raise_not_implemented("reindex_file")


@mcp.tool(
    description=(
        "Remove one file's chunks from the index. Use this after deleting or "
        "renaming an indexed file."
    )
)
def delete_file_from_index(file_path: str) -> dict[str, object]:
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
    query: str,
    max_results: int = 5,
    include_stale: bool = False,
) -> list[dict[str, object]]:
    _raise_not_implemented("search_repo_context")


@mcp.tool(description="Return debugging information about the current index.")
def get_index_status(repo_path: str | None = None) -> dict[str, object]:
    _raise_not_implemented("get_index_status")

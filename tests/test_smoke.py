"""End-to-end lifecycle smoke tests for the codebase-indexer MCP server.

These tests dispatch through ``server.mcp.call_tool`` against a real
ChromaDB store using the default local embedding function, so first-run
model download cost is expected. They are opt-in via the ``smoke`` marker;
run with ``pipenv run pytest -m smoke``.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from codebase_indexer import server

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "smoke_repo"


def _call(tool_name: str, arguments: dict[str, object]) -> dict | list:
    result = asyncio.run(server.mcp.call_tool(tool_name, arguments))
    assert result.is_error is False, f"{tool_name} returned an error: {result}"
    return json.loads(result.content[0].text)


def _copy_fixture(destination: Path) -> Path:
    shutil.copytree(FIXTURE_REPO, destination)
    return destination


pytestmark = pytest.mark.smoke


def test_smoke_dev_workflow(tmp_path: Path) -> None:
    """Exercise the enforced dev workflow: index, reconcile stale, search, edit, reindex."""
    repo = _copy_fixture(tmp_path / "repo")

    initialized = _call("index_repo", {"repo_path": str(repo)})
    assert initialized["status"] == "initialized"
    assert initialized["created"] is True
    assert initialized["chunks_indexed"] > 0

    math_ops = repo / "pkg" / "math_ops.py"
    math_ops.write_text(
        math_ops.read_text(encoding="utf-8")
        + "\n\ndef marker_out_of_band_edit() -> str:\n    return 'edited outside the tool'\n",
        encoding="utf-8",
    )

    drifted = _call("get_index_status", {"repo_path": str(repo)})
    assert drifted["status"] == "changes_detected"
    assert drifted["files_to_reindex"] == [
        {"relative_path": "pkg/math_ops.py", "reason": "content_changed"}
    ]
    assert drifted["files_to_delete"] == []

    reconciled = _call(
        "reindex_file",
        {"repo_path": str(repo), "file_path": "pkg/math_ops.py"},
    )
    assert reconciled["status"] == "reindexed"
    assert reconciled["relative_path"] == "pkg/math_ops.py"

    clean = _call("get_index_status", {"repo_path": str(repo)})
    assert clean["status"] == "clean"
    assert clean["files_to_reindex"] == []
    assert clean["files_to_delete"] == []
    assert clean["files_with_errors"] == []

    matches = _call(
        "search_repo_context",
        {"repo_path": str(repo), "query": "compute_fibonacci", "max_results": 1},
    )
    assert isinstance(matches, list) and matches
    assert matches[0]["relative_path"] == "pkg/math_ops.py"
    assert matches[0]["stale"] is False

    math_ops.write_text(
        math_ops.read_text(encoding="utf-8")
        + "\n\ndef marker_agent_edit() -> str:\n    return 'edited after reading pointers'\n",
        encoding="utf-8",
    )

    reindexed_after_edit = _call(
        "reindex_file",
        {"repo_path": str(repo), "file_path": "pkg/math_ops.py"},
    )
    assert reindexed_after_edit["status"] == "reindexed"

    final = _call("get_index_status", {"repo_path": str(repo)})
    assert final["status"] == "clean"
    assert final["files_to_reindex"] == []
    assert final["files_to_delete"] == []


def test_smoke_cleanup_workflow(tmp_path: Path) -> None:
    """Exercise the cleanup path: detect deletion, remove entry, tear down the index."""
    repo = _copy_fixture(tmp_path / "repo")

    initialized = _call("index_repo", {"repo_path": str(repo)})
    assert initialized["status"] == "initialized"
    assert initialized["chunks_indexed"] > 0

    (repo / "pkg" / "strings.py").unlink()

    drifted = _call("get_index_status", {"repo_path": str(repo)})
    assert drifted["status"] == "changes_detected"
    assert drifted["files_to_delete"] == [
        {"relative_path": "pkg/strings.py", "reason": "missing"}
    ]
    assert drifted["files_to_reindex"] == []

    deleted = _call(
        "delete_file_from_index",
        {"repo_path": str(repo), "file_path": "pkg/strings.py"},
    )
    assert deleted["status"] == "deleted"
    assert deleted["relative_path"] == "pkg/strings.py"
    assert deleted["chunks_removed"] >= 1

    clean = _call("get_index_status", {"repo_path": str(repo)})
    assert clean["status"] == "clean"
    assert clean["files_to_delete"] == []
    assert clean["files_to_reindex"] == []

    index_dir = repo / ".codebase-index"
    assert index_dir.exists()

    removed = _call(
        "remove_index",
        {"repo_path": str(repo), "confirm": True},
    )
    assert removed["status"] == "removed"
    assert not index_dir.exists()

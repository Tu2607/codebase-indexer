import asyncio
import inspect
import json
from unittest.mock import Mock

import pytest
from fastmcp.exceptions import ToolError

import codebase_indexer.server as server
from codebase_indexer.indexer import IndexPartialFailureError
from codebase_indexer.index_store import IndexCorruptedError, IndexNotInitializedError


def _patch_open_store(monkeypatch, store):
    open_existing = Mock(return_value=store)
    monkeypatch.setattr(server.IndexStore, "open_existing", open_existing)
    return open_existing


def test_index_repo_creates_new_store_and_delegates_to_indexer(monkeypatch, tmp_path):
    store = Mock()
    store.index_dir = tmp_path / ".codebase-index"
    index_store_class = Mock(return_value=store)
    index_store_class.open_existing = Mock(
        side_effect=IndexNotInitializedError("not initialized")
    )
    monkeypatch.setattr(server, "IndexStore", index_store_class)
    orchestrator = Mock(
        return_value={
            "status": "initialized",
            "repo_path": str(tmp_path.resolve()),
            "index_path": str(store.index_dir),
            "created": True,
            "files_indexed": 2,
            "chunks_indexed": 3,
            "files_skipped": 1,
        }
    )
    monkeypatch.setattr(server, "index_repository", orchestrator)

    result = server.index_repo(str(tmp_path))

    assert result == orchestrator.return_value
    index_store_class.open_existing.assert_called_once_with(tmp_path.resolve())
    index_store_class.assert_called_once_with(tmp_path.resolve())
    orchestrator.assert_called_once_with(store, tmp_path.resolve())


def test_index_repo_returns_without_walking_healthy_existing_index(
    monkeypatch,
    tmp_path,
):
    store = Mock()
    store.index_dir = tmp_path / ".codebase-index"
    open_existing = _patch_open_store(monkeypatch, store)
    orchestrator = Mock()
    monkeypatch.setattr(server, "index_repository", orchestrator)

    result = server.index_repo(str(tmp_path))

    assert result == {
        "status": "initialized",
        "repo_path": str(tmp_path.resolve()),
        "index_path": str(store.index_dir),
        "created": False,
    }
    open_existing.assert_called_once_with(tmp_path.resolve())
    orchestrator.assert_not_called()


def test_index_repo_converts_corrupted_index_error_to_tool_error(
    monkeypatch,
    tmp_path,
):
    open_existing = Mock(side_effect=IndexCorruptedError("run rebuild_index"))
    monkeypatch.setattr(server.IndexStore, "open_existing", open_existing)

    with pytest.raises(ToolError, match="rebuild_index"):
        server.index_repo(str(tmp_path))

    open_existing.assert_called_once_with(tmp_path.resolve())


@pytest.mark.parametrize("repo_path", [None, "", " ", "missing"])
def test_index_repo_rejects_invalid_repository_path(repo_path):
    with pytest.raises(ToolError, match="repo_path"):
        server.index_repo(repo_path)


def test_index_repo_converts_store_creation_value_error_to_tool_error(
    monkeypatch,
    tmp_path,
):
    index_store_class = Mock(side_effect=ValueError("index cannot be created"))
    index_store_class.open_existing = Mock(
        side_effect=IndexNotInitializedError("not initialized")
    )
    monkeypatch.setattr(server, "IndexStore", index_store_class)

    with pytest.raises(ToolError, match="index cannot be created"):
        server.index_repo(str(tmp_path))


def test_index_repo_propagates_unexpected_open_existing_error(monkeypatch, tmp_path):
    error = RuntimeError("unexpected index failure")
    open_existing = Mock(side_effect=error)
    monkeypatch.setattr(server.IndexStore, "open_existing", open_existing)

    with pytest.raises(RuntimeError, match="unexpected index failure"):
        server.index_repo(str(tmp_path))


def test_index_repo_converts_partial_failure_to_tool_error(monkeypatch, tmp_path):
    store = Mock()
    store.index_dir = tmp_path / ".codebase-index"
    index_store_class = Mock(return_value=store)
    index_store_class.open_existing = Mock(
        side_effect=IndexNotInitializedError("not initialized")
    )
    monkeypatch.setattr(server, "IndexStore", index_store_class)
    error = IndexPartialFailureError('{"status": "partial_failure"}')
    orchestrator = Mock(side_effect=error)
    monkeypatch.setattr(server, "index_repository", orchestrator)

    with pytest.raises(ToolError, match="partial_failure"):
        server.index_repo(str(tmp_path))

    orchestrator.assert_called_once_with(store, tmp_path.resolve())


def test_reindex_file_wires_store_and_orchestrator(monkeypatch, tmp_path):
    store = Mock()
    store.repo_path = tmp_path.resolve()
    open_existing = _patch_open_store(monkeypatch, store)
    orchestrator = Mock(
        return_value={
            "status": "reindexed",
            "relative_path": "module.py",
            "file_hash": "a" * 64,
            "chunks_added": 1,
            "chunks_removed": 0,
        }
    )
    monkeypatch.setattr(server, "reindex_single_file", orchestrator)

    result = server.reindex_file(str(tmp_path), "module.py")

    assert result == orchestrator.return_value
    open_existing.assert_called_once_with(tmp_path.resolve())
    orchestrator.assert_called_once_with(store, "module.py", tmp_path.resolve())


@pytest.mark.parametrize("error_message", ["run index_repo", "index disappeared"])
def test_reindex_file_converts_index_initialization_errors_to_tool_error(
    monkeypatch,
    tmp_path,
    error_message,
):
    open_existing = Mock(side_effect=IndexNotInitializedError(error_message))
    monkeypatch.setattr(server.IndexStore, "open_existing", open_existing)

    with pytest.raises(ToolError, match=error_message):
        server.reindex_file(str(tmp_path), "module.py")

    open_existing.assert_called_once_with(tmp_path.resolve())


def test_reindex_file_converts_corrupted_index_error_to_tool_error(
    monkeypatch,
    tmp_path,
):
    error = IndexCorruptedError("run rebuild_index")
    open_existing = Mock(side_effect=error)
    monkeypatch.setattr(server.IndexStore, "open_existing", open_existing)

    with pytest.raises(ToolError, match="rebuild_index"):
        server.reindex_file(str(tmp_path), "module.py")

    open_existing.assert_called_once_with(tmp_path.resolve())


@pytest.mark.parametrize("repo_path", [None, "", " ", "missing"])
def test_reindex_file_rejects_invalid_repository_path(repo_path):
    with pytest.raises(ToolError, match="repo_path"):
        server.reindex_file(repo_path, "module.py")


def test_reindex_file_converts_path_error_to_tool_error(monkeypatch, tmp_path):
    store = Mock()
    store.repo_path = tmp_path.resolve()
    _patch_open_store(monkeypatch, store)
    monkeypatch.setattr(
        server,
        "reindex_single_file",
        Mock(side_effect=ValueError("file_path resolves outside repo_path")),
    )

    with pytest.raises(ToolError, match="outside repo_path"):
        server.reindex_file(str(tmp_path), "../outside.py")


def test_reindex_file_strips_whitespace_from_repository_path(monkeypatch, tmp_path):
    store = Mock()
    store.repo_path = tmp_path.resolve()
    open_existing = _patch_open_store(monkeypatch, store)
    orchestrator = Mock(return_value={"status": "file_not_found"})
    monkeypatch.setattr(server, "reindex_single_file", orchestrator)

    assert server.reindex_file(f" {tmp_path} ", "module.py") == {
        "status": "file_not_found"
    }
    open_existing.assert_called_once_with(tmp_path.resolve())


def test_reindex_file_strips_whitespace_from_file_path(monkeypatch, tmp_path):
    store = Mock()
    store.repo_path = tmp_path.resolve()
    _patch_open_store(monkeypatch, store)
    orchestrator = Mock(return_value={"status": "file_not_found"})
    monkeypatch.setattr(server, "reindex_single_file", orchestrator)

    server.reindex_file(str(tmp_path), " module.py ")

    assert orchestrator.call_args.args[1] == "module.py"


@pytest.mark.parametrize("file_path", [None, "", " "])
def test_reindex_file_rejects_empty_file_path(monkeypatch, tmp_path, file_path):
    open_existing = Mock()
    monkeypatch.setattr(server.IndexStore, "open_existing", open_existing)

    with pytest.raises(ToolError, match="file_path is required"):
        server.reindex_file(str(tmp_path), file_path)

    open_existing.assert_not_called()


def test_reindex_file_converts_plain_open_existing_value_error_to_tool_error(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        server.IndexStore,
        "open_existing",
        Mock(side_effect=ValueError("corrupt metadata")),
    )

    with pytest.raises(ToolError, match="corrupt metadata"):
        server.reindex_file(str(tmp_path), "module.py")


def test_reindex_file_rejects_file_as_repository_path(tmp_path):
    repo_path = tmp_path / "not-a-repository"
    repo_path.write_text("content\n", encoding="utf-8")

    with pytest.raises(ToolError, match="existing directory"):
        server.reindex_file(str(repo_path), "module.py")


def test_reindex_file_does_not_swallow_unexpected_orchestrator_errors(
    monkeypatch,
    tmp_path,
):
    store = Mock()
    store.repo_path = tmp_path.resolve()
    _patch_open_store(monkeypatch, store)
    monkeypatch.setattr(
        server,
        "reindex_single_file",
        Mock(side_effect=RuntimeError("unexpected failure")),
    )

    with pytest.raises(RuntimeError, match="unexpected failure"):
        server.reindex_file(str(tmp_path), "module.py")


def test_fastmcp_dispatches_reindex_file_for_empty_indexable_file(tmp_path):
    from codebase_indexer.index_store import IndexStore

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / "module.py").write_text("", encoding="utf-8")
    IndexStore(repo_path)

    result = asyncio.run(
        server.mcp.call_tool(
            "reindex_file",
            {"repo_path": str(repo_path), "file_path": "module.py"},
        )
    )

    assert result.is_error is False
    assert result.content[0].text


@pytest.mark.parametrize(
    ("file_path", "create_file", "expected_status"),
    [
        ("missing.py", False, "file_not_found"),
        ("image.png", True, "not_indexable"),
    ],
)
def test_fastmcp_reindex_reports_non_mutating_file_states(
    tmp_path,
    file_path,
    create_file,
    expected_status,
):
    from codebase_indexer.index_store import IndexStore

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    if create_file:
        (repo_path / file_path).write_bytes(b"content")
    IndexStore(repo_path)

    result = asyncio.run(
        server.mcp.call_tool(
            "reindex_file",
            {"repo_path": str(repo_path), "file_path": file_path},
        )
    )

    assert result.is_error is False
    assert json.loads(result.content[0].text)["status"] == expected_status


def test_fastmcp_returns_error_for_uninitialized_repository(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    with pytest.raises(ToolError, match="index_repo"):
        asyncio.run(
            server.mcp.call_tool(
                "reindex_file",
                {"repo_path": str(repo_path), "file_path": "module.py"},
            )
        )


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        (
            "delete_file_from_index",
            {"repo_path": "/tmp/repo", "file_path": "module.py"},
        ),
        (
            "search_repo_context",
            {"repo_path": "/tmp/repo", "query": "module"},
        ),
    ],
)
def test_scaffolded_index_tools_raise_tool_error(tool_name, arguments):
    with pytest.raises(ToolError, match="scaffolded but not implemented"):
        asyncio.run(server.mcp.call_tool(tool_name, arguments))


def test_server_tool_signatures_use_explicit_repo_path():
    assert list(inspect.signature(server.index_repo).parameters) == ["repo_path"]
    assert inspect.signature(server.reindex_file).parameters.keys() >= {
        "repo_path",
        "file_path",
    }
    assert list(inspect.signature(server.delete_file_from_index).parameters) == [
        "repo_path",
        "file_path",
    ]
    assert list(inspect.signature(server.search_repo_context).parameters) == [
        "repo_path",
        "query",
        "max_results",
        "include_stale",
    ]

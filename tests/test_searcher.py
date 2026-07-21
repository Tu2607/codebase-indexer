from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

import codebase_indexer.searcher as searcher
from codebase_indexer.hashing import hash_file
from codebase_indexer.searcher import SearchMetadataError, search_repository


@dataclass
class FakeIndexStore:
    metadata: list[dict[str, object] | None]
    queries: list[tuple[str, int]] = field(default_factory=list)

    def query_chunks(
        self,
        query_text: str,
        n_results: int,
    ) -> list[dict[str, object] | None]:
        self.queries.append((query_text, n_results))
        return self.metadata


def _metadata(
    relative_path: str,
    file_hash: str,
    *,
    start_line: object = 1,
    end_line: object = 10,
) -> dict[str, object]:
    return {
        "relative_path": relative_path,
        "start_line": start_line,
        "end_line": end_line,
        "file_hash": file_hash,
    }


def test_search_repository_returns_fresh_source_pointer(tmp_path):
    file_path = tmp_path / "module.py"
    file_path.write_text("content\n", encoding="utf-8")
    store = FakeIndexStore([_metadata("module.py", hash_file(file_path))])

    result = search_repository(store, tmp_path, "module", 10, False)

    assert result == [
        {
            "relative_path": "module.py",
            "start_line": 1,
            "end_line": 10,
            "stale": False,
        }
    ]
    assert store.queries == [("module", 10)]


@pytest.mark.parametrize("include_stale", [False, True])
@pytest.mark.parametrize("file_state", ["changed", "missing", "unreadable"])
def test_search_repository_filters_or_includes_stale_matches(
    monkeypatch,
    tmp_path,
    file_state,
    include_stale,
):
    file_path = tmp_path / "module.py"
    if file_state != "missing":
        file_path.write_text("current\n", encoding="utf-8")
    if file_state == "unreadable":
        monkeypatch.setattr(
            searcher,
            "hash_file",
            lambda path: (_ for _ in ()).throw(OSError("unreadable")),
        )
    store = FakeIndexStore([_metadata("module.py", "stored-hash")])

    result = search_repository(store, tmp_path, "module", 10, include_stale)

    expected = []
    if include_stale:
        expected = [
            {
                "relative_path": "module.py",
                "start_line": 1,
                "end_line": 10,
                "stale": True,
            }
        ]
    assert result == expected


def test_search_repository_preserves_order_after_filtering(tmp_path):
    first = tmp_path / "first.py"
    third = tmp_path / "third.py"
    first.write_text("first\n", encoding="utf-8")
    third.write_text("third\n", encoding="utf-8")
    store = FakeIndexStore(
        [
            _metadata("first.py", hash_file(first), start_line=1, end_line=5),
            _metadata("missing.py", "missing", start_line=6, end_line=10),
            _metadata("third.py", hash_file(third), start_line=11, end_line=15),
        ]
    )

    result = search_repository(store, tmp_path, "ordered", 3, False)

    assert [match["relative_path"] for match in result] == [
        "first.py",
        "third.py",
    ]


def test_search_repository_hashes_each_file_once_per_call(monkeypatch, tmp_path):
    file_path = tmp_path / "module.py"
    file_path.write_text("content\n", encoding="utf-8")
    current_hash = hash_file(file_path)
    store = FakeIndexStore(
        [
            _metadata("module.py", current_hash, start_line=1, end_line=10),
            _metadata("module.py", current_hash, start_line=11, end_line=20),
        ]
    )
    hash_calls = []

    def record_hash(path):
        hash_calls.append(path)
        return current_hash

    monkeypatch.setattr(searcher, "hash_file", record_hash)

    result = search_repository(store, tmp_path, "module", 10, False)

    assert len(result) == 2
    assert hash_calls == [file_path.resolve()]


def test_search_repository_does_not_overfetch_after_stale_filtering(tmp_path):
    store = FakeIndexStore([_metadata("missing.py", "stored-hash")])

    assert search_repository(store, tmp_path, "module", 10, False) == []
    assert store.queries == [("module", 10)]


def test_search_repository_returns_empty_list_for_no_candidates(tmp_path):
    store = FakeIndexStore([])

    assert search_repository(store, tmp_path, "module", 10, False) == []


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        (None, "missing or invalid"),
        ({}, "relative_path"),
        (_metadata("", "hash"), "relative_path"),
        (_metadata("module.py", ""), "file_hash"),
        (_metadata("module.py", "hash", start_line="1"), "start_line"),
        (_metadata("module.py", "hash", start_line=True), "start_line"),
        (_metadata("module.py", "hash", start_line=0), "start_line"),
        (_metadata("module.py", "hash", start_line=2, end_line=1), "end_line"),
        (_metadata("module.py", "hash", end_line=False), "end_line"),
    ],
)
def test_search_repository_rejects_malformed_metadata(
    tmp_path,
    metadata,
    message,
):
    store = FakeIndexStore([metadata])

    with pytest.raises(SearchMetadataError, match=message):
        search_repository(store, tmp_path, "module", 10, False)


@pytest.mark.parametrize(
    "relative_path",
    ["../outside.py", ".", "./module.py", "src/../module.py"],
)
def test_search_repository_rejects_unsafe_or_non_normalized_path(
    tmp_path,
    relative_path,
):
    store = FakeIndexStore([_metadata(relative_path, "hash")])

    with pytest.raises(SearchMetadataError, match="relative_path"):
        search_repository(store, tmp_path, "module", 10, False)


def test_search_repository_rejects_symlink_escape(tmp_path):
    outside_path = tmp_path.parent / "outside.py"
    outside_path.write_text("outside\n", encoding="utf-8")
    link_path = tmp_path / "link.py"
    try:
        link_path.symlink_to(outside_path)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")
    store = FakeIndexStore([_metadata("link.py", hash_file(outside_path))])

    with pytest.raises(SearchMetadataError, match="outside repo_path"):
        search_repository(store, tmp_path, "module", 10, False)


def test_search_repository_validates_all_metadata_before_hashing(monkeypatch, tmp_path):
    file_path = tmp_path / "valid.py"
    file_path.write_text("content\n", encoding="utf-8")
    store = FakeIndexStore(
        [
            _metadata("valid.py", hash_file(file_path)),
            _metadata("invalid.py", "hash", start_line=0),
        ]
    )
    hash_mock = lambda path: pytest.fail("hashing should not start")
    monkeypatch.setattr(searcher, "hash_file", hash_mock)

    with pytest.raises(SearchMetadataError, match="start_line"):
        search_repository(store, tmp_path, "module", 10, False)

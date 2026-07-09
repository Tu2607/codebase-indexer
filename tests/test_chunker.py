from pathlib import Path

import pytest

import codebase_indexer.chunker as chunker
from codebase_indexer.chunker import TextChunk, chunk_by_lines
from codebase_indexer.repo_id import repo_path_hash


FILE_HASH = "a" * 64


def test_chunk_by_lines_returns_single_chunk_with_metadata(tmp_path):
    repo_path = tmp_path / "repo"
    file_path = repo_path / "src" / "example.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("first line\nsecond line\n", encoding="utf-8")

    chunks = chunk_by_lines(file_path, repo_path=repo_path, file_hash=FILE_HASH)

    assert chunks == [
        TextChunk(
            id=f"{repo_path_hash(repo_path)}:src/example.py:0:{FILE_HASH[:12]}",
            document="first line\nsecond line\n",
            metadata={
                "repo_path": str(repo_path.resolve()),
                "file_path": str(file_path.resolve()),
                "relative_path": "src/example.py",
                "start_line": 1,
                "end_line": 2,
                "file_hash": FILE_HASH,
                "chunk_index": 0,
            },
        )
    ]


def test_chunk_by_lines_uses_overlapping_windows_with_correct_line_numbers(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    file_path = repo_path / "module.py"
    file_path.write_text("".join(f"line {number}\n" for number in range(1, 7)))

    chunks = chunk_by_lines(
        file_path,
        repo_path=repo_path,
        file_hash=FILE_HASH,
        chunk_size=3,
        overlap=1,
    )

    assert [chunk.document for chunk in chunks] == [
        "line 1\nline 2\nline 3\n",
        "line 3\nline 4\nline 5\n",
        "line 5\nline 6\n",
    ]
    assert [chunk.metadata["start_line"] for chunk in chunks] == [1, 3, 5]
    assert [chunk.metadata["end_line"] for chunk in chunks] == [3, 5, 6]
    assert [chunk.metadata["chunk_index"] for chunk in chunks] == [0, 1, 2]


def test_chunk_by_lines_does_not_add_overlap_only_chunk_for_exact_size(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    file_path = repo_path / "module.py"
    file_path.write_text("one\ntwo\nthree\n", encoding="utf-8")

    chunks = chunk_by_lines(
        file_path,
        repo_path=repo_path,
        file_hash=FILE_HASH,
        chunk_size=3,
        overlap=1,
    )

    assert len(chunks) == 1


def test_chunk_by_lines_allows_zero_overlap(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    file_path = repo_path / "module.py"
    file_path.write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")

    chunks = chunk_by_lines(
        file_path,
        repo_path=repo_path,
        file_hash=FILE_HASH,
        chunk_size=2,
        overlap=0,
    )

    assert [chunk.document for chunk in chunks] == ["one\ntwo\n", "three\nfour\n", "five\n"]
    assert [chunk.metadata["start_line"] for chunk in chunks] == [1, 3, 5]


def test_chunk_by_lines_returns_empty_list_for_empty_file(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    file_path = repo_path / "empty.py"
    file_path.write_text("", encoding="utf-8")

    assert chunk_by_lines(file_path, repo_path=repo_path, file_hash=FILE_HASH) == []


def test_chunk_by_lines_includes_last_line_without_trailing_newline(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    file_path = repo_path / "module.py"
    file_path.write_text("first\nlast", encoding="utf-8")

    chunks = chunk_by_lines(
        file_path,
        repo_path=repo_path,
        file_hash=FILE_HASH,
        chunk_size=1,
        overlap=0,
    )

    assert [chunk.document for chunk in chunks] == ["first\n", "last"]
    assert chunks[-1].metadata["end_line"] == 2


@pytest.mark.parametrize(
    ("chunk_size", "overlap", "message"),
    [
        (0, 0, "chunk_size must be positive"),
        (-1, 0, "chunk_size must be positive"),
        (1, -1, "overlap must be non-negative"),
        (1, 1, "overlap must be less than chunk_size"),
    ],
)
def test_chunk_by_lines_rejects_invalid_settings_before_reading(
    monkeypatch,
    tmp_path,
    chunk_size,
    overlap,
    message,
):
    def fail_open(*args, **kwargs):
        raise AssertionError("open should not be called")

    monkeypatch.setattr(Path, "open", fail_open)

    with pytest.raises(ValueError, match=message):
        chunk_by_lines(
            tmp_path / "missing.py",
            repo_path=tmp_path,
            file_hash=FILE_HASH,
            chunk_size=chunk_size,
            overlap=overlap,
        )


def test_chunk_by_lines_rejects_file_outside_repo_before_reading(monkeypatch, tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    outside_path = tmp_path / "outside.py"

    def fail_open(*args, **kwargs):
        raise AssertionError("open should not be called")

    monkeypatch.setattr(Path, "open", fail_open)

    with pytest.raises(ValueError, match="file_path is not inside repo_path"):
        chunk_by_lines(outside_path, repo_path=repo_path, file_hash=FILE_HASH)


def test_chunk_by_lines_rejects_symlink_that_resolves_outside_repo(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    outside_path = tmp_path / "outside.py"
    outside_path.write_text("outside\n", encoding="utf-8")
    file_path = repo_path / "linked.py"

    try:
        file_path.symlink_to(outside_path)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(ValueError, match="file_path is not inside repo_path"):
        chunk_by_lines(file_path, repo_path=repo_path, file_hash=FILE_HASH)


def test_chunk_by_lines_propagates_file_not_found_error(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    with pytest.raises(FileNotFoundError):
        chunk_by_lines(repo_path / "missing.py", repo_path=repo_path, file_hash=FILE_HASH)


def test_chunk_by_lines_accepts_string_and_pathlike_arguments(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    file_path = repo_path / "module.py"
    file_path.write_text("content\n", encoding="utf-8")

    from_strings = chunk_by_lines(
        str(file_path), repo_path=str(repo_path), file_hash=FILE_HASH
    )
    from_paths = chunk_by_lines(file_path, repo_path=repo_path, file_hash=FILE_HASH)

    assert from_strings == from_paths


def test_chunk_by_lines_replaces_invalid_utf8_bytes(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    file_path = repo_path / "invalid.py"
    file_path.write_bytes(b"valid\n\xffinvalid\n")

    chunks = chunk_by_lines(file_path, repo_path=repo_path, file_hash=FILE_HASH)

    assert chunks[0].document == "valid\n\ufffdinvalid\n"


def test_chunk_by_lines_preserves_line_endings(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    file_path = repo_path / "mixed-endings.py"
    file_path.write_bytes(b"first\r\nsecond\nthird\r\n")

    chunks = chunk_by_lines(file_path, repo_path=repo_path, file_hash=FILE_HASH)

    assert chunks[0].document == "first\r\nsecond\nthird\r\n"


def test_chunk_by_lines_ids_are_stable_and_include_file_hash_prefix(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    file_path = repo_path / "module.py"
    file_path.write_text("content\n", encoding="utf-8")

    first_chunks = chunk_by_lines(file_path, repo_path=repo_path, file_hash=FILE_HASH)
    second_chunks = chunk_by_lines(file_path, repo_path=repo_path, file_hash=FILE_HASH)

    assert first_chunks[0].id == second_chunks[0].id
    assert first_chunks[0].id.endswith(f":{FILE_HASH[:12]}")

    changed_hash_chunks = chunk_by_lines(
        file_path, repo_path=repo_path, file_hash="b" * 64
    )

    assert first_chunks[0].id != changed_hash_chunks[0].id


def test_chunker_public_surface():
    assert chunker.__all__ == ["TextChunk", "chunk_by_lines"]

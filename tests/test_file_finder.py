import os

import pytest

import codebase_indexer.file_finder as file_finder
from codebase_indexer.config import MAX_FILE_SIZE_BYTES
from codebase_indexer.file_finder import should_index_file


def test_should_index_regular_file(tmp_path):
    file_path = tmp_path / "module.py"
    file_path.write_text("content\n", encoding="utf-8")

    assert should_index_file(file_path, tmp_path) == (True, None)


def test_should_index_exact_filename(tmp_path):
    file_path = tmp_path / "Dockerfile"
    file_path.write_text("FROM scratch\n", encoding="utf-8")

    assert should_index_file(file_path, tmp_path) == (True, None)


def test_should_index_rejects_unsupported_extension(tmp_path):
    file_path = tmp_path / "image.png"
    file_path.write_bytes(b"content")

    assert should_index_file(file_path, tmp_path) == (
        False,
        "unsupported file type: image.png",
    )


def test_should_index_rejects_oversized_file(tmp_path):
    file_path = tmp_path / "large.py"
    file_path.write_bytes(b"x" * (MAX_FILE_SIZE_BYTES + 1))

    assert should_index_file(file_path, tmp_path) == (
        False,
        f"file too large: {MAX_FILE_SIZE_BYTES + 1} bytes, "
        f"limit {MAX_FILE_SIZE_BYTES} bytes",
    )


def test_should_index_accepts_file_at_size_limit(tmp_path):
    file_path = tmp_path / "limit.py"
    file_path.write_bytes(b"x" * MAX_FILE_SIZE_BYTES)

    assert should_index_file(file_path, tmp_path) == (True, None)


def test_should_index_rejects_file_in_skipped_directory(tmp_path):
    file_path = tmp_path / "src" / "node_modules" / "module.js"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("content\n", encoding="utf-8")

    assert should_index_file(file_path, tmp_path) == (
        False,
        "inside skipped directory: node_modules",
    )


def test_should_index_rejects_exact_filename_in_skipped_directory(tmp_path):
    file_path = tmp_path / "node_modules" / "Dockerfile"
    file_path.parent.mkdir()
    file_path.write_text("FROM scratch\n", encoding="utf-8")

    assert should_index_file(file_path, tmp_path) == (
        False,
        "inside skipped directory: node_modules",
    )


def test_should_index_ignores_skipped_name_when_it_is_the_filename(tmp_path):
    file_path = tmp_path / "build"
    file_path.write_text("content\n", encoding="utf-8")

    assert should_index_file(file_path, tmp_path) == (
        False,
        "unsupported file type: build",
    )


def test_should_index_rejects_non_regular_file(tmp_path):
    file_path = tmp_path / "pipe.py"

    try:
        os.mkfifo(file_path)
    except (AttributeError, NotImplementedError, OSError) as exc:
        pytest.skip(f"FIFO creation is unavailable: {exc}")

    assert should_index_file(file_path, tmp_path) == (False, "not a regular file")


def test_should_index_accepts_symlink_to_regular_file(tmp_path):
    target = tmp_path / "target.py"
    target.write_text("content\n", encoding="utf-8")
    file_path = tmp_path / "linked.py"

    try:
        file_path.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    assert should_index_file(file_path, tmp_path) == (True, None)


def test_should_index_propagates_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        should_index_file(tmp_path / "missing.py", tmp_path)


def test_should_index_propagates_file_not_found_for_broken_symlink(tmp_path):
    file_path = tmp_path / "broken.py"

    try:
        file_path.symlink_to(tmp_path / "missing.py")
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(FileNotFoundError):
        should_index_file(file_path, tmp_path)


def test_should_index_rejects_file_outside_repo(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    file_path = tmp_path / "outside.py"
    file_path.write_text("content\n", encoding="utf-8")

    with pytest.raises(ValueError, match="is not in the subpath"):
        should_index_file(file_path, repo_path)


def test_file_finder_public_surface():
    assert file_finder.__all__ == ["should_index_file"]

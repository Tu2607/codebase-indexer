import os

import pytest

import codebase_indexer.file_finder as file_finder
from codebase_indexer.config import MAX_FILE_SIZE_BYTES
from codebase_indexer.file_finder import iter_indexable_files, should_index_file


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


def test_iter_indexable_files_discovers_files_in_stable_order(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "src" / "module.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "src" / "app.js").write_text("const app = {}\n", encoding="utf-8")
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"image")

    eligible_files, skipped_count = iter_indexable_files(tmp_path)

    assert [relative_path for _, relative_path in eligible_files] == [
        "docs/guide.md",
        "src/app.js",
        "src/module.py",
    ]
    assert [path for path, _ in eligible_files] == [
        (tmp_path / relative_path).resolve()
        for _, relative_path in eligible_files
    ]
    assert skipped_count == 1


def test_iter_indexable_files_returns_empty_for_no_eligible_files(tmp_path):
    (tmp_path / "image.png").write_bytes(b"image")
    (tmp_path / "program.exe").write_bytes(b"program")

    assert iter_indexable_files(tmp_path) == ([], 2)


def test_iter_indexable_files_prunes_skipped_directories(tmp_path):
    skipped_directory = tmp_path / "src" / "node_modules"
    skipped_directory.mkdir(parents=True)
    (skipped_directory / "package.js").write_text("content\n", encoding="utf-8")
    (tmp_path / "module.py").write_text("content\n", encoding="utf-8")

    eligible_files, skipped_count = iter_indexable_files(tmp_path)

    assert eligible_files == [((tmp_path / "module.py").resolve(), "module.py")]
    assert skipped_count == 0


def test_iter_indexable_files_does_not_follow_symlinked_directories(tmp_path):
    target = tmp_path.parent / f"{tmp_path.name}-target"
    target.mkdir()
    (target / "external.py").write_text("content\n", encoding="utf-8")

    try:
        (tmp_path / "linked").symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    assert iter_indexable_files(tmp_path) == ([], 0)


def test_iter_indexable_files_deduplicates_file_symlinks(tmp_path):
    target = tmp_path / "z-real.py"
    target.write_text("content\n", encoding="utf-8")

    try:
        (tmp_path / "a-linked.py").symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    assert iter_indexable_files(tmp_path) == ([(target.resolve(), "z-real.py")], 1)


def test_iter_indexable_files_skips_file_symlink_outside_repo(tmp_path):
    target = tmp_path.parent / f"{tmp_path.name}-external.py"
    target.write_text("content\n", encoding="utf-8")

    try:
        (tmp_path / "linked.py").symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    assert iter_indexable_files(tmp_path) == ([], 1)


def test_iter_indexable_files_skips_symlink_into_skipped_directory(tmp_path):
    target_directory = tmp_path / "node_modules"
    target_directory.mkdir()
    target = target_directory / "hidden.py"
    target.write_text("content\n", encoding="utf-8")

    try:
        (tmp_path / "linked.py").symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    assert iter_indexable_files(tmp_path) == ([], 1)


def test_iter_indexable_files_counts_broken_symlink_as_skipped(tmp_path):
    try:
        (tmp_path / "broken.py").symlink_to(tmp_path / "missing.py")
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    assert iter_indexable_files(tmp_path) == ([], 1)


def test_iter_indexable_files_counts_filtering_oserror_as_skipped(
    tmp_path, monkeypatch
):
    inaccessible = tmp_path / "inaccessible.py"
    inaccessible.write_text("content\n", encoding="utf-8")
    indexable = tmp_path / "module.py"
    indexable.write_text("content\n", encoding="utf-8")
    original_should_index_file = file_finder.should_index_file

    def raise_for_inaccessible(file_path, repo_path):
        if file_path == inaccessible:
            raise PermissionError("permission denied")
        return original_should_index_file(file_path, repo_path)

    monkeypatch.setattr(file_finder, "should_index_file", raise_for_inaccessible)

    assert iter_indexable_files(tmp_path) == ([(indexable.resolve(), "module.py")], 1)


def test_iter_indexable_files_counts_oversized_file_as_skipped(tmp_path):
    (tmp_path / "large.py").write_bytes(b"x" * (MAX_FILE_SIZE_BYTES + 1))

    assert iter_indexable_files(tmp_path) == ([], 1)


def test_iter_indexable_files_handles_empty_repository(tmp_path):
    assert iter_indexable_files(tmp_path) == ([], 0)


def test_file_finder_public_surface():
    assert file_finder.__all__ == ["iter_indexable_files", "should_index_file"]

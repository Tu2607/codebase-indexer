import hashlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import codebase_indexer.hashing as hashing
from codebase_indexer.hashing import FileChangedDuringHashingError, hash_file


EMPTY_SHA256 = (
    "e3b0c44298fc1c149afbf4c8996fb924"
    "27ae41e4649b934ca495991b7852b855"
)
HELLO_WORLD_SHA256 = (
    "b94d27b9934d3e08a52e52d7da7dabfa"
    "c484efe37a5380ee9088f7ace2efcde9"
)


def test_hash_file_hashes_known_input(tmp_path):
    path = tmp_path / "example.txt"
    path.write_bytes(b"hello world")

    assert hash_file(path) == HELLO_WORLD_SHA256


def test_hash_file_hashes_empty_file(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")

    assert hash_file(path) == EMPTY_SHA256


def test_hash_file_identical_content_matches(tmp_path):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_bytes(b"print('same')\n")
    second.write_bytes(b"print('same')\n")

    assert hash_file(first) == hash_file(second)


def test_hash_file_changes_when_file_bytes_change(tmp_path):
    path = tmp_path / "module.py"
    path.write_bytes(b"before\n")
    before = hash_file(path)

    path.write_bytes(b"after\n")

    assert hash_file(path) != before


def test_hash_file_streams_files_larger_than_read_buffer(tmp_path):
    content = b"abc123\n" * 10_000
    assert len(content) > 64 * 1024

    path = tmp_path / "large.txt"
    path.write_bytes(content)

    assert hash_file(path) == hashlib.sha256(content).hexdigest()


def test_hash_file_missing_path_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        hash_file(tmp_path / "missing.py")


def test_hash_file_directory_raises_without_opening(monkeypatch, tmp_path):
    directory = tmp_path / "directory"
    directory.mkdir()

    open_spy = Mock(wraps=hashing.Path.open)
    monkeypatch.setattr(hashing.Path, "open", open_spy)

    with pytest.raises(IsADirectoryError):
        hash_file(directory)

    open_spy.assert_not_called()


def test_hash_file_broken_symlink_raises_os_error(tmp_path):
    link = tmp_path / "broken-link"

    try:
        link.symlink_to(tmp_path / "missing-target")
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(OSError) as exc_info:
        hash_file(link)

    assert not isinstance(exc_info.value, FileNotFoundError)


def test_hash_file_symlink_to_regular_file_hashes_target(tmp_path):
    target = tmp_path / "target.txt"
    target.write_bytes(b"target bytes\n")
    link = tmp_path / "target-link"

    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    assert hash_file(link) == hash_file(target)


def test_hash_file_accepts_str_and_pathlike(tmp_path):
    path = tmp_path / "pathlike.txt"
    path.write_bytes(b"pathlike\n")

    assert hash_file(str(path)) == hash_file(path)


def test_hash_file_raises_when_size_changes_during_hashing(monkeypatch, tmp_path):
    path = tmp_path / "changing-size.txt"
    path.write_bytes(b"content\n")
    calls = []

    def fake_stat(file_path):
        calls.append(file_path)
        if len(calls) == 1:
            return SimpleNamespace(st_size=8, st_mtime_ns=100)
        return SimpleNamespace(st_size=9, st_mtime_ns=100)

    monkeypatch.setattr(hashing, "_stat_for_consistency", fake_stat)

    with pytest.raises(FileChangedDuringHashingError) as exc_info:
        hash_file(path)

    assert str(path) in str(exc_info.value)
    assert "st_size" in str(exc_info.value)
    assert calls == [path, path]


def test_hash_file_raises_when_mtime_changes_during_hashing(monkeypatch, tmp_path):
    path = tmp_path / "changing-mtime.txt"
    path.write_bytes(b"content\n")

    def fake_stat(file_path):
        if fake_stat.calls == 0:
            fake_stat.calls += 1
            return SimpleNamespace(st_size=8, st_mtime_ns=100)
        fake_stat.calls += 1
        return SimpleNamespace(st_size=8, st_mtime_ns=101)

    fake_stat.calls = 0
    monkeypatch.setattr(hashing, "_stat_for_consistency", fake_stat)

    with pytest.raises(FileChangedDuringHashingError) as exc_info:
        hash_file(path)

    assert str(path) in str(exc_info.value)
    assert "st_mtime_ns" in str(exc_info.value)
    assert fake_stat.calls == 2


def test_hash_file_stable_read_has_no_false_positive(tmp_path):
    path = tmp_path / "stable.txt"
    path.write_bytes(b"stable\n")

    assert hash_file(path) == hash_file(path)


def test_file_changed_during_hashing_error_is_os_error():
    assert issubclass(FileChangedDuringHashingError, OSError)


def test_hashing_public_surface():
    assert hashing.__all__ == ["hash_file", "FileChangedDuringHashingError"]

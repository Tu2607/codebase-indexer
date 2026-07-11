import pytest

import codebase_indexer.path_utils as path_utils
from codebase_indexer.path_utils import resolve_repo_file_path, validate_repo_path


def test_validate_repo_path_resolves_and_strips_string_path(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    assert validate_repo_path(f" {repo_path} ") == repo_path.resolve()


def test_validate_repo_path_accepts_path_object(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    assert validate_repo_path(repo_path) == repo_path.resolve()


@pytest.mark.parametrize("repo_path", [None, "", " "])
def test_validate_repo_path_rejects_empty_path(repo_path):
    with pytest.raises(ValueError, match="repo_path is required"):
        validate_repo_path(repo_path)


def test_validate_repo_path_rejects_missing_path(tmp_path):
    with pytest.raises(ValueError, match="existing directory"):
        validate_repo_path(tmp_path / "missing")


def test_validate_repo_path_rejects_file_path(tmp_path):
    repo_path = tmp_path / "not-a-repo"
    repo_path.write_text("content\n", encoding="utf-8")

    with pytest.raises(ValueError, match="existing directory"):
        validate_repo_path(repo_path)


def test_resolve_repo_file_path_resolves_relative_path_against_repo(tmp_path):
    repo_path = tmp_path / "repo"
    file_path = repo_path / "src" / "module.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("content\n", encoding="utf-8")

    assert resolve_repo_file_path(repo_path, "src/module.py") == (
        repo_path.resolve(),
        file_path.resolve(),
        "src/module.py",
    )


def test_resolve_repo_file_path_accepts_absolute_path_inside_repo(tmp_path):
    repo_path = tmp_path / "repo"
    file_path = repo_path / "module.py"
    repo_path.mkdir()
    file_path.write_text("content\n", encoding="utf-8")

    assert resolve_repo_file_path(repo_path, file_path) == (
        repo_path.resolve(),
        file_path.resolve(),
        "module.py",
    )


def test_resolve_repo_file_path_accepts_string_arguments(tmp_path):
    repo_path = tmp_path / "repo"
    file_path = repo_path / "module.py"
    repo_path.mkdir()
    file_path.write_text("content\n", encoding="utf-8")

    assert resolve_repo_file_path(str(repo_path), str(file_path)) == (
        repo_path.resolve(),
        file_path.resolve(),
        "module.py",
    )


def test_resolve_repo_file_path_normalizes_relative_path_components(tmp_path):
    repo_path = tmp_path / "repo"
    file_path = repo_path / "src" / "module.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("content\n", encoding="utf-8")

    assert resolve_repo_file_path(repo_path, "src/../src/module.py") == (
        repo_path.resolve(),
        file_path.resolve(),
        "src/module.py",
    )


def test_resolve_repo_file_path_allows_missing_file_inside_repo(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    missing_path = repo_path / "src" / "deleted.py"

    assert resolve_repo_file_path(repo_path, "src/deleted.py") == (
        repo_path.resolve(),
        missing_path,
        "src/deleted.py",
    )


def test_resolve_repo_file_path_rejects_absolute_path_outside_repo(tmp_path):
    repo_path = tmp_path / "repo"
    outside_path = tmp_path / "outside.py"
    repo_path.mkdir()
    outside_path.write_text("content\n", encoding="utf-8")

    with pytest.raises(ValueError, match="resolves outside repo_path"):
        resolve_repo_file_path(repo_path, outside_path)


def test_resolve_repo_file_path_rejects_relative_path_outside_repo(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    with pytest.raises(ValueError, match="resolves outside repo_path"):
        resolve_repo_file_path(repo_path, "../outside.py")


def test_resolve_repo_file_path_rejects_deep_traversal_through_missing_paths(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    with pytest.raises(ValueError, match="resolves outside repo_path"):
        resolve_repo_file_path(repo_path, "a/b/../../c/../../../outside.py")


def test_resolve_repo_file_path_rejects_symlink_outside_repo(tmp_path):
    repo_path = tmp_path / "repo"
    outside_path = tmp_path / "outside.py"
    linked_path = repo_path / "linked.py"
    repo_path.mkdir()
    outside_path.write_text("content\n", encoding="utf-8")

    try:
        linked_path.symlink_to(outside_path)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(ValueError, match="resolves outside repo_path"):
        resolve_repo_file_path(repo_path, linked_path)


def test_resolve_repo_file_path_rejects_symlinked_directory_outside_repo(tmp_path):
    repo_path = tmp_path / "repo"
    outside_dir = tmp_path / "outside"
    linked_dir = repo_path / "linked-dir"
    outside_file = outside_dir / "secret.py"
    repo_path.mkdir()
    outside_dir.mkdir()
    outside_file.write_text("content\n", encoding="utf-8")

    try:
        linked_dir.symlink_to(outside_dir, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(ValueError, match="resolves outside repo_path"):
        resolve_repo_file_path(repo_path, "linked-dir/secret.py")


def test_resolve_repo_file_path_accepts_symlink_inside_repo(tmp_path):
    repo_path = tmp_path / "repo"
    target_path = repo_path / "target.py"
    linked_path = repo_path / "linked.py"
    repo_path.mkdir()
    target_path.write_text("content\n", encoding="utf-8")

    try:
        linked_path.symlink_to(target_path)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    assert resolve_repo_file_path(repo_path, linked_path) == (
        repo_path.resolve(),
        target_path.resolve(),
        "target.py",
    )


def test_resolve_repo_file_path_resolves_symlinked_repo_path(tmp_path):
    target_path = tmp_path / "repo"
    link_path = tmp_path / "repo-link"
    file_path = target_path / "module.py"
    target_path.mkdir()
    file_path.write_text("content\n", encoding="utf-8")

    try:
        link_path.symlink_to(target_path, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    assert resolve_repo_file_path(link_path, "module.py") == (
        target_path.resolve(),
        file_path.resolve(),
        "module.py",
    )


def test_resolve_repo_file_path_rejects_missing_repo_path(tmp_path):
    with pytest.raises(ValueError, match="existing directory"):
        resolve_repo_file_path(tmp_path / "missing", "module.py")


def test_resolve_repo_file_path_rejects_file_as_repo_path(tmp_path):
    repo_path = tmp_path / "not-a-repo"
    repo_path.write_text("content\n", encoding="utf-8")

    with pytest.raises(ValueError, match="existing directory"):
        resolve_repo_file_path(repo_path, "module.py")


@pytest.mark.parametrize("file_path", ["", "."])
def test_resolve_repo_file_path_rejects_repository_root(tmp_path, file_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    with pytest.raises(ValueError, match="must not resolve to the repository root"):
        resolve_repo_file_path(repo_path, file_path)


def test_path_utils_public_surface():
    assert path_utils.__all__ == ["resolve_repo_file_path", "validate_repo_path"]

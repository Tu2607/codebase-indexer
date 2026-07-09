import hashlib
import re

import codebase_indexer.repo_id as repo_id
from codebase_indexer.repo_id import repo_path_hash


def test_repo_path_hash_matches_resolved_path_sha256(tmp_path):
    expected = hashlib.sha256(str(tmp_path.resolve()).encode("utf-8")).hexdigest()[:12]

    assert repo_path_hash(tmp_path) == expected


def test_repo_path_hash_is_deterministic(tmp_path):
    assert repo_path_hash(tmp_path) == repo_path_hash(tmp_path)


def test_repo_path_hash_is_twelve_lowercase_hex_characters(tmp_path):
    assert re.fullmatch(r"[0-9a-f]{12}", repo_path_hash(tmp_path))


def test_repo_path_hash_accepts_string_and_pathlike(tmp_path):
    assert repo_path_hash(str(tmp_path)) == repo_path_hash(tmp_path)


def test_repo_path_hash_resolves_relative_paths(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path.parent)

    assert repo_path_hash(tmp_path.name) == repo_path_hash(tmp_path)


def test_repo_id_public_surface():
    assert repo_id.__all__ == ["repo_path_hash"]

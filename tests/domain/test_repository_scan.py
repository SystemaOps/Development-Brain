"""Unit tests for repository scanning domain model."""

from __future__ import annotations

from brain.domain.identity import new_repository_id
from brain.domain.repository_scan import (
    FileCategory,
    RepositoryChangeSet,
    RepositorySnapshot,
    classify_changed_files,
    classify_file,
)


class TestFileClassification:
    def test_manifest_names(self) -> None:
        assert classify_file("pyproject.toml") is FileCategory.MANIFEST
        assert classify_file("package.json") is FileCategory.MANIFEST
        assert classify_file("requirements.txt") is FileCategory.MANIFEST

    def test_deployment_beats_generic_config(self) -> None:
        assert classify_file("docker-compose.yml") is FileCategory.DEPLOYMENT
        assert classify_file(".gitlab-ci.yml") is FileCategory.DEPLOYMENT
        assert classify_file("Dockerfile") is FileCategory.DEPLOYMENT

    def test_test_beats_source(self) -> None:
        assert classify_file("tests/test_app.py") is FileCategory.TEST
        assert classify_file("src/app_test.py") is FileCategory.TEST
        assert classify_file("pkg/spec/app_spec.ts") is FileCategory.TEST

    def test_documentation(self) -> None:
        assert classify_file("README.md") is FileCategory.DOCUMENTATION
        assert classify_file("docs/architecture.md") is FileCategory.DOCUMENTATION
        assert classify_file("CHANGELOG.rst") is FileCategory.DOCUMENTATION

    def test_schema(self) -> None:
        assert classify_file("migrations/0001.sql") is FileCategory.SCHEMA
        assert classify_file("proto/user.proto") is FileCategory.SCHEMA

    def test_source_and_config(self) -> None:
        assert classify_file("src/main.py") is FileCategory.SOURCE
        assert classify_file("src/util.js") is FileCategory.SOURCE
        assert classify_file("settings.json") is FileCategory.CONFIGURATION

    def test_unknown(self) -> None:
        assert classify_file("assets/logo.png") is FileCategory.UNKNOWN


class TestClassifyChangedFiles:
    def test_preserves_order_and_paths(self) -> None:
        paths = ["src/app.py", "docs/readme.md", "tests/test_app.py"]
        changed = classify_changed_files(paths)
        assert [c.path for c in changed] == paths
        assert [c.category for c in changed] == [
            FileCategory.SOURCE,
            FileCategory.DOCUMENTATION,
            FileCategory.TEST,
        ]

    def test_empty_input(self) -> None:
        assert classify_changed_files([]) == []


class TestSnapshotAndChangeSetModels:
    def test_snapshot_round_trips(self) -> None:
        snapshot = RepositorySnapshot(
            repository_id=new_repository_id(),
            revision="abc123",
            tree=["src/main.py", "README.md"],
            languages=["Python"],
            manifest_files=["pyproject.toml"],
            documentation_roots=["README.md"],
        )
        restored = RepositorySnapshot.model_validate(snapshot.model_dump(mode="json"))
        assert restored == snapshot

    def test_change_set_round_trips(self) -> None:
        change_set = RepositoryChangeSet(
            repository_id=new_repository_id(),
            old_revision="old",
            new_revision="new",
            files=classify_changed_files(["src/app.py", "README.md"]),
        )
        restored = RepositoryChangeSet.model_validate(change_set.model_dump(mode="json"))
        assert restored == change_set
        assert restored.files[0].category is FileCategory.SOURCE

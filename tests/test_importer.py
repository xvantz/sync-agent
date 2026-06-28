"""Tests for importer.py — Pull Mirror import logic."""

from __future__ import annotations

from unittest.mock import Mock

from sync_agent.forgejo_client import ForgejoClient
from sync_agent.importer import Importer
from sync_agent.platforms.base import PlatformRepo
from sync_agent.reconciler import DiffResult


class TestImporter:
    def test_import_all_missing(self) -> None:
        forgejo = Mock(spec=ForgejoClient)
        forgejo.migrate_repo.return_value = Mock(
            name="test-repo",
            mirror=True,
            id=42,
        )

        gh_provider = Mock()
        gh_provider.name = "github"
        gh_provider._client = object()

        platforms = {"github": gh_provider}
        importer = Importer(forgejo, platforms)

        diff = DiffResult(
            missing_in_forgejo=[
                (
                    "github",
                    PlatformRepo(
                        name="test-repo",
                        owner="xvantz",
                        clone_url="https://github.com/xvantz/test-repo.git",
                        private=True,
                        description="A test repo",
                        platform="github",
                    ),
                ),
            ],
        )

        count = importer.run(diff)

        assert count == 1
        forgejo.migrate_repo.assert_called_once_with(
            clone_addr="https://github.com/xvantz/test-repo.git",
            repo_name="test-repo",
            mirror=True,
            private=True,
            description="A test repo",
            auth_token=None,
        )

    def test_dry_run_does_not_import(self) -> None:
        forgejo = Mock(spec=ForgejoClient)
        gh_provider = Mock()
        gh_provider.name = "github"
        gh_provider._client = object()

        importer = Importer(forgejo, {"github": gh_provider})

        diff = DiffResult(
            missing_in_forgejo=[
                (
                    "github",
                    PlatformRepo(
                        name="some-repo",
                        owner="xvantz",
                        clone_url="https://github.com/xvantz/some-repo.git",
                        private=True,
                        description="",
                        platform="github",
                    ),
                ),
            ],
        )

        count = importer.run(diff, dry_run=True)

        assert count == 1
        forgejo.migrate_repo.assert_not_called()

    def test_empty_diff_does_nothing(self) -> None:
        forgejo = Mock(spec=ForgejoClient)
        importer = Importer(forgejo, {})

        diff = DiffResult()
        count = importer.run(diff)

        assert count == 0
        forgejo.migrate_repo.assert_not_called()

    def test_unknown_platform_skipped(self) -> None:
        forgejo = Mock(spec=ForgejoClient)
        importer = Importer(forgejo, {})

        diff = DiffResult(
            missing_in_forgejo=[
                (
                    "unknown-platform",
                    PlatformRepo(
                        name="test", owner="x",
                        clone_url="https://x.com/x/test.git",
                        private=True, description="",
                        platform="unknown",
                    ),
                ),
            ],
        )

        count = importer.run(diff)
        assert count == 0
        forgejo.migrate_repo.assert_not_called()

    def test_import_error_logged_continues(self) -> None:
        forgejo = Mock(spec=ForgejoClient)
        forgejo.migrate_repo.side_effect = Exception("API error")

        gh_provider = Mock()
        gh_provider.name = "github"
        gh_provider._client = object()

        importer = Importer(forgejo, {"github": gh_provider})

        diff = DiffResult(
            missing_in_forgejo=[
                (
                    "github",
                    PlatformRepo(
                        name="repo-a", owner="x",
                        clone_url="https://github.com/x/repo-a.git",
                        private=True, description="",
                        platform="github",
                    ),
                ),
                (
                    "github",
                    PlatformRepo(
                        name="repo-b", owner="x",
                        clone_url="https://github.com/x/repo-b.git",
                        private=True, description="",
                        platform="github",
                    ),
                ),
            ],
        )

        count = importer.run(diff)
        assert count == 0  # both failed
        assert forgejo.migrate_repo.call_count == 2

"""Tests for reconciler.py — discovery + diff logic."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

from sync_agent.forgejo_client import ForgejoClient
from sync_agent.platforms.github import GitHubProvider
from sync_agent.platforms.codeberg import CodebergProvider
from sync_agent.reconciler import Reconciler


class TestReconciler:
    def test_discover_no_diff(
        self,
        forgejo_repos: list[dict[str, Any]],
        forgejo_client: ForgejoClient,
    ) -> None:
        """When all cloud repos already exist in Forgejo, diff should be empty."""
        # Mock Forgejo client
        forgejo_client._client.get = Mock(
            side_effect=[
                # list_repos
                Mock(status_code=200, json=lambda: forgejo_repos),
            ]
        )
        # Mock Forgejo list_push_mirrors — empty (no mirrors yet)
        forgejo_client.list_push_mirrors = Mock(return_value=[])

        # Mock GitHub provider — same repos as Forgejo
        gh_provider = Mock(spec=GitHubProvider)
        gh_provider.name = "github"
        gh_provider.list_repos.return_value = []
        gh_provider.ssh_push_url.return_value = "git@github.com:xvantz/hashgrid.git"

        platforms = {"github": gh_provider}
        reconciler = Reconciler(forgejo_client, platforms)
        diff = reconciler.discover()

        assert len(diff.missing_in_forgejo) == 0

    def test_discover_missing_in_forgejo(
        self,
        forgejo_repos: list[dict[str, Any]],
        forgejo_client: ForgejoClient,
        github_repos: list[dict[str, Any]],
    ) -> None:
        """Repos that exist on GitHub but not in Forgejo should appear in diff."""
        forgejo_client._client.get = Mock(
            side_effect=[
                Mock(status_code=200, json=lambda: forgejo_repos),
            ]
        )
        forgejo_client.list_push_mirrors = Mock(return_value=[])

        # GitHub has "resume" which is NOT in Forgejo repos
        def _gh_repos():
            from sync_agent.platforms.base import PlatformRepo

            return [
                PlatformRepo(
                    name=r["name"],
                    owner=r["owner"]["login"],
                    clone_url=r["clone_url"],
                    private=r["private"],
                    description=r.get("description", ""),
                    platform="github",
                )
                for r in github_repos
            ]

        gh_provider = Mock(spec=GitHubProvider)
        gh_provider.name = "github"
        gh_provider.list_repos = _gh_repos

        platforms = {"github": gh_provider}
        reconciler = Reconciler(forgejo_client, platforms)
        diff = reconciler.discover()

        assert len(diff.missing_in_forgejo) == 1
        platform_name, repo = diff.missing_in_forgejo[0]
        assert platform_name == "github"
        assert repo.name == "resume"
        assert repo.owner == "xvantz"

    def test_discover_missing_push_mirrors(
        self,
        forgejo_repos: list[dict[str, Any]],
        forgejo_client: ForgejoClient,
    ) -> None:
        """Repos without push mirrors to targets should be detected."""
        forgejo_client._client.get = Mock(
            side_effect=[
                Mock(status_code=200, json=lambda: forgejo_repos),
            ]
        )

        # hashgrid has a push mirror to github, coolcontrol has none
        def _list_mirrors(owner: str, repo: str) -> list[dict]:
            if repo == "hashgrid":
                return [
                    {
                        "remote_name": "github",
                        "remote_address": "git@github.com:xvantz/hashgrid.git",
                    }
                ]
            return []

        forgejo_client.list_push_mirrors = _list_mirrors

        def _gh_repos():
            from sync_agent.platforms.base import PlatformRepo

            return [
                PlatformRepo(
                    name=r["name"],
                    owner=r["owner"]["login"],
                    clone_url=r["clone_url"],
                    private=r["private"],
                    description=r.get("description", ""),
                    platform="github",
                )
                for r in forgejo_repos
            ]

        gh_provider = Mock(spec=GitHubProvider)
        gh_provider.name = "github"
        gh_provider.list_repos = _gh_repos

        platforms = {"github": gh_provider}
        reconciler = Reconciler(forgejo_client, platforms)
        diff = reconciler.discover()

        assert len(diff.missing_push_mirrors) == 1
        repo, targets = diff.missing_push_mirrors[0]
        assert repo.name == "coolcontrol"
        assert "github" in targets

    def test_discover_multiple_platforms(
        self,
        forgejo_repos: list[dict[str, Any]],
        forgejo_client: ForgejoClient,
        github_repos: list[dict[str, Any]],
        codeberg_repos: list[dict[str, Any]],
    ) -> None:
        """Diff should aggregate missing repos across all platforms."""
        # Forgejo has: hashgrid, coolcontrol
        forgejo_client._client.get = Mock(
            side_effect=[
                Mock(status_code=200, json=lambda: forgejo_repos),
            ]
        )
        forgejo_client.list_push_mirrors = Mock(return_value=[])

        def _gh_repos():
            from sync_agent.platforms.base import PlatformRepo

            return [
                PlatformRepo(
                    name=r["name"],
                    owner=r["owner"]["login"],
                    clone_url=r["clone_url"],
                    private=r["private"],
                    description=r["description"],
                    platform="github",
                )
                for r in github_repos
            ]

        def _cb_repos():
            from sync_agent.platforms.base import PlatformRepo

            return [
                PlatformRepo(
                    name=r["name"],
                    owner=r["owner"]["login"],
                    clone_url=r["clone_url"],
                    private=r.get("private", True),
                    description=r["description"],
                    platform="codeberg",
                )
                for r in codeberg_repos
            ]

        gh_provider = Mock(spec=GitHubProvider)
        gh_provider.name = "github"
        gh_provider.list_repos = _gh_repos

        cb_provider = Mock(spec=CodebergProvider)
        cb_provider.name = "codeberg"
        cb_provider.list_repos = _cb_repos

        platforms = {"github": gh_provider, "codeberg": cb_provider}
        reconciler = Reconciler(forgejo_client, platforms)
        diff = reconciler.discover()

        # resume (github) + dotfiles (codeberg)
        assert len(diff.missing_in_forgejo) == 2
        names = {r.name for _, r in diff.missing_in_forgejo}
        assert names == {"resume", "dotfiles"}
        assert diff.platform_counts.get("github", 0) == 2
        assert diff.platform_counts.get("codeberg", 0) == 1

    def test_discover_platform_counts(
        self,
        forgejo_repos: list[dict[str, Any]],
        forgejo_client: ForgejoClient,
        github_repos: list[dict[str, Any]],
    ) -> None:
        """Platform counts should be reported correctly."""
        forgejo_client._client.get = Mock(
            side_effect=[
                Mock(status_code=200, json=lambda: forgejo_repos),
            ]
        )
        forgejo_client.list_push_mirrors = Mock(return_value=[])

        def _gh_repos():
            from sync_agent.platforms.base import PlatformRepo

            return [
                PlatformRepo(
                    name=r["name"],
                    owner=r["owner"]["login"],
                    clone_url=r["clone_url"],
                    private=r["private"],
                    description=r["description"],
                    platform="github",
                )
                for r in github_repos
            ]

        gh_provider = Mock(spec=GitHubProvider)
        gh_provider.name = "github"
        gh_provider.list_repos = _gh_repos

        platforms = {"github": gh_provider}
        reconciler = Reconciler(forgejo_client, platforms)
        diff = reconciler.discover()

        assert diff.platform_counts == {"github": 2}

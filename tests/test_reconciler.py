"""Tests for reconciler.py — discovery + diff logic."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

from sync_agent.forgejo_client import ForgejoClient
from sync_agent.platforms.github import GitHubProvider
from sync_agent.platforms.codeberg import CodebergProvider
from sync_agent.reconciler import Reconciler


class TestReconciler:
    def _make_forgejo_repos(self) -> list[dict[str, Any]]:
        return [
            {
                "id": 1,
                "name": "hashgrid",
                "full_name": "xvantz/hashgrid",
                "owner": {"login": "xvantz", "id": 100},
                "clone_url": "http://localhost:2000/xvantz/hashgrid.git",
                "mirror": False,
                "empty": False,
                "private": True,
                "description": "Spatial engine",
            },
            {
                "id": 2,
                "name": "coolcontrol",
                "full_name": "xvantz/coolcontrol",
                "owner": {"login": "xvantz", "id": 100},
                "clone_url": "http://localhost:2000/xvantz/coolcontrol.git",
                "mirror": True,
                "empty": False,
                "private": True,
                "description": "Fan control",
            },
        ]

    def _make_cloud_repos(
        self, names: list[str], platform: str = "github"
    ) -> list[dict[str, Any]]:
        """Create cloud repo dicts similar to what providers return."""
        return [
            {
                "name": name,
                "owner": {"login": "xvantz"},
                "clone_url": (
                    f"https://{platform}.com/xvantz/{name}.git"
                ),
                "private": True,
                "description": f"Repo {name}",
            }
            for name in names
        ]

    def test_discover_no_diff(self) -> None:
        """When all cloud repos already exist in Forgejo, diff should be empty."""
        fj_repos = self._make_forgejo_repos()

        forgejo = ForgejoClient("http://localhost:2000", "token")
        forgejo._client.get = Mock(return_value=fj_repos)
        forgejo._client.post = Mock()
        forgejo.list_push_mirrors = Mock(return_value=[])

        # GitHub has nothing extra — same repos as Forgejo
        gh_provider = Mock(spec=GitHubProvider)
        gh_provider.name = "github"
        gh_provider.list_repos = Mock(return_value=[])

        reconciler = Reconciler(forgejo, {"github": gh_provider})
        diff = reconciler.discover()

        assert len(diff.missing_in_forgejo) == 0

    def test_discover_missing_in_forgejo(self) -> None:
        """Repos that exist on GitHub but not in Forgejo should appear."""
        fj_repos = self._make_forgejo_repos()

        forgejo = ForgejoClient("http://localhost:2000", "token")
        forgejo._client.get = Mock(return_value=fj_repos)
        forgejo._client.post = Mock()
        forgejo.list_push_mirrors = Mock(return_value=[])

        from sync_agent.platforms.base import PlatformRepo

        gh_provider = Mock(spec=GitHubProvider)
        gh_provider.name = "github"
        gh_provider.list_repos = Mock(
            return_value=[
                PlatformRepo(
                    name="resume",
                    owner="xvantz",
                    clone_url="https://github.com/xvantz/resume.git",
                    private=False,
                    description="My resume",
                    platform="github",
                ),
            ]
        )

        reconciler = Reconciler(forgejo, {"github": gh_provider})
        diff = reconciler.discover()

        assert len(diff.missing_in_forgejo) == 1
        platform_name, repo = diff.missing_in_forgejo[0]
        assert platform_name == "github"
        assert repo.name == "resume"

    def test_discover_missing_push_mirrors(self) -> None:
        """Repos without push mirrors to targets should be detected."""
        fj_repos = self._make_forgejo_repos()

        forgejo = ForgejoClient("http://localhost:2000", "token")
        forgejo._client.get = Mock(return_value=fj_repos)
        forgejo._client.post = Mock()

        # hashgrid has push mirror to github (with sync_on_commit), coolcontrol has none
        def _list_mirrors(owner: str, repo: str) -> list[dict]:
            if repo == "hashgrid":
                return [
                    {
                        "remote_name": "github",
                        "remote_address": (
                            "git@github.com:xvantz/hashgrid.git"
                        ),
                        "sync_on_commit": True,
                    }
                ]
            return []

        forgejo.list_push_mirrors = _list_mirrors

        from sync_agent.platforms.base import PlatformRepo

        gh_provider = Mock(spec=GitHubProvider)
        gh_provider.name = "github"
        gh_provider.list_repos = Mock(
            return_value=[
                PlatformRepo(
                    name=r["name"],
                    owner="xvantz",
                    clone_url=r["clone_url"],
                    private=r["private"],
                    description=r.get("description", ""),
                    platform="github",
                )
                for r in fj_repos
            ]
        )

        reconciler = Reconciler(forgejo, {"github": gh_provider})
        diff = reconciler.discover()

        assert len(diff.missing_push_mirrors) == 1
        repo, targets = diff.missing_push_mirrors[0]
        assert repo.name == "coolcontrol"
        assert "github" in targets

    def test_discover_multiple_platforms(self) -> None:
        """Diff should aggregate missing repos across all platforms."""
        fj_repos = self._make_forgejo_repos()

        forgejo = ForgejoClient("http://localhost:2000", "token")
        forgejo._client.get = Mock(return_value=fj_repos)
        forgejo._client.post = Mock()
        forgejo.list_push_mirrors = Mock(return_value=[])

        from sync_agent.platforms.base import PlatformRepo

        gh_provider = Mock(spec=GitHubProvider)
        gh_provider.name = "github"
        gh_provider.list_repos = Mock(
            return_value=[
                PlatformRepo(
                    name="resume",
                    owner="xvantz",
                    clone_url="https://github.com/xvantz/resume.git",
                    private=False,
                    description="My resume",
                    platform="github",
                ),
            ]
        )

        cb_provider = Mock(spec=CodebergProvider)
        cb_provider.name = "codeberg"
        cb_provider.list_repos = Mock(
            return_value=[
                PlatformRepo(
                    name="dotfiles",
                    owner="xvantz",
                    clone_url="https://codeberg.org/xvantz/dotfiles.git",
                    private=False,
                    description="NixOS dotfiles",
                    platform="codeberg",
                ),
            ]
        )

        reconciler = Reconciler(
            forgejo, {"github": gh_provider, "codeberg": cb_provider}
        )
        diff = reconciler.discover()

        assert len(diff.missing_in_forgejo) == 2
        names = {r.name for _, r in diff.missing_in_forgejo}
        assert names == {"resume", "dotfiles"}

    def test_discover_platform_counts(self) -> None:
        """Platform counts should be reported correctly."""
        fj_repos = self._make_forgejo_repos()

        forgejo = ForgejoClient("http://localhost:2000", "token")
        forgejo._client.get = Mock(return_value=fj_repos)
        forgejo._client.post = Mock()
        forgejo.list_push_mirrors = Mock(return_value=[])

        from sync_agent.platforms.base import PlatformRepo

        gh_provider = Mock(spec=GitHubProvider)
        gh_provider.name = "github"
        gh_provider.list_repos = Mock(
            return_value=[
                PlatformRepo(
                    name="hashgrid",
                    owner="xvantz",
                    clone_url="https://github.com/xvantz/hashgrid.git",
                    private=True,
                    description="Spatial engine",
                    platform="github",
                ),
                PlatformRepo(
                    name="resume",
                    owner="xvantz",
                    clone_url="https://github.com/xvantz/resume.git",
                    private=False,
                    description="My resume",
                    platform="github",
                ),
            ]
        )

        reconciler = Reconciler(forgejo, {"github": gh_provider})
        diff = reconciler.discover()

        assert diff.platform_counts == {"github": 2}

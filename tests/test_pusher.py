"""Tests for pusher.py — Push Mirror setup logic."""

from __future__ import annotations

from unittest.mock import Mock

from sync_agent.forgejo_client import ForgejoClient, ForgejoRepo
from sync_agent.pusher import Pusher
from sync_agent.reconciler import DiffResult


class TestPusher:
    def test_adds_missing_push_mirrors(self) -> None:
        forgejo = Mock(spec=ForgejoClient)
        forgejo.add_push_mirror.return_value = {"remote_name": "github"}
        forgejo.list_push_mirrors.return_value = []

        gh_provider = Mock()
        gh_provider.name = "github"
        gh_provider._client = object()  # no token -> falls back to SSH
        gh_provider.repo_exists.return_value = True  # repo exists on GitHub

        pusher = Pusher(forgejo, {"github": gh_provider})

        diff = DiffResult(
            missing_push_mirrors=[
                (
                    ForgejoRepo(
                        id=1, name="coolcontrol",
                        full_name="xvantz/coolcontrol",
                        owner="xvantz",
                        clone_url="http://localhost:2000/xvantz/coolcontrol.git",
                        mirror=False, empty=False,
                        private=True, description="Fan control",
                    ),
                    ["github"],
                ),
            ],
        )

        count = pusher.run(diff)

        assert count == 1
        forgejo.add_push_mirror.assert_called_once_with(
            "xvantz", "coolcontrol",
            "git@github.com:xvantz/coolcontrol.git",
        )

    def test_dry_run_does_not_add(self) -> None:
        forgejo = Mock(spec=ForgejoClient)
        gh_provider = Mock()
        gh_provider._client = object()
        pusher = Pusher(forgejo, {"github": gh_provider})

        diff = DiffResult(
            missing_push_mirrors=[
                (
                    ForgejoRepo(
                        id=1, name="repo", full_name="x/repo",
                        owner="x",
                        clone_url="http://localhost:2000/x/repo.git",
                        mirror=False, empty=False,
                        private=True, description="",
                    ),
                    ["github"],
                ),
            ],
        )

        count = pusher.run(diff, dry_run=True)

        assert count == 1
        forgejo.add_push_mirror.assert_not_called()

    def test_no_missing_mirrors(self) -> None:
        forgejo = Mock(spec=ForgejoClient)
        pusher = Pusher(forgejo, {})
        diff = DiffResult()
        count = pusher.run(diff)
        assert count == 0
        forgejo.add_push_mirror.assert_not_called()

    def test_unknown_target_skipped(self) -> None:
        forgejo = Mock(spec=ForgejoClient)
        pusher = Pusher(forgejo, {})
        diff = DiffResult(
            missing_push_mirrors=[
                (
                    ForgejoRepo(
                        id=1, name="r", full_name="x/r",
                        owner="x",
                        clone_url="http://localhost:2000/x/r.git",
                        mirror=False, empty=False,
                        private=True, description="",
                    ),
                    ["unknown-platform"],
                ),
            ],
        )
        count = pusher.run(diff)
        assert count == 0

    def test_repo_creation_failure_skips_mirror(self) -> None:
        """When repo doesn't exist on target and can't be created, skip push mirror."""
        forgejo = Mock(spec=ForgejoClient)
        forgejo.list_push_mirrors.return_value = []

        gh_provider = Mock()
        gh_provider.name = "github"
        gh_provider._client = object()
        gh_provider.repo_exists.return_value = False   # repo missing
        gh_provider.create_repo.side_effect = Exception("no permission")  # can't create

        pusher = Pusher(forgejo, {"github": gh_provider})

        diff = DiffResult(
            missing_push_mirrors=[
                (
                    ForgejoRepo(
                        id=1, name="a", full_name="x/a",
                        owner="x",
                        clone_url="http://localhost:2000/x/a.git",
                        mirror=False, empty=False,
                        private=True, description="",
                    ),
                    ["github"],
                ),
            ],
        )

        count = pusher.run(diff)
        assert count == 0
        forgejo.add_push_mirror.assert_not_called()
        gh_provider.create_repo.assert_called_once()

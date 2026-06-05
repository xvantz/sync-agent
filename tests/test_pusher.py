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

        gh_provider = Mock()
        gh_provider.name = "github"

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
        pusher = Pusher(forgejo, {"github": Mock()})

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

    def test_empty_diff_does_nothing(self) -> None:
        forgejo = Mock(spec=ForgejoClient)
        pusher = Pusher(forgejo, {})
        count = pusher.run(DiffResult())
        assert count == 0
        forgejo.add_push_mirror.assert_not_called()

    def test_multiple_targets(self) -> None:
        forgejo = Mock(spec=ForgejoClient)
        forgejo.add_push_mirror.return_value = {}

        gh = Mock(); gh.name = "github"
        cb = Mock(); cb.name = "codeberg"

        pusher = Pusher(forgejo, {"github": gh, "codeberg": cb})

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
                    ["github", "codeberg"],
                ),
            ],
        )

        count = pusher.run(diff)

        assert count == 2
        assert forgejo.add_push_mirror.call_count == 2

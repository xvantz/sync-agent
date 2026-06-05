"""Tests for forgejo_client.py — Forgejo API client."""

from __future__ import annotations

from typing import Any
from unittest.mock import ANY, Mock, patch

import httpx
import pytest

from sync_agent.forgejo_client import ForgejoClient, ForgejoRepo


class TestForgejoClient:
    """Tests using mocked httpx responses."""

    def test_list_repos(self, forgejo_repos: list[dict[str, Any]]) -> None:
        client = ForgejoClient("http://localhost:2000", "token")
        mock_resp = Mock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = forgejo_repos

        with patch.object(client._client, "get", return_value=mock_resp):
            repos = client.list_repos()

        assert len(repos) == 2
        assert repos[0].name == "hashgrid"
        assert repos[0].owner == "xvantz"
        assert repos[1].name == "coolcontrol"

    def test_list_repos_for_user(
        self, forgejo_repos: list[dict[str, Any]]
    ) -> None:
        client = ForgejoClient("http://localhost:2000", "token")
        mock_resp = Mock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = forgejo_repos

        with patch.object(client._client, "get", return_value=mock_resp) as mock_get:
            client.list_repos(user="xvantz")

        mock_get.assert_called_once_with("/api/v1/users/xvantz/repos")

    def test_get_repo(self) -> None:
        client = ForgejoClient("http://localhost:2000", "token")
        mock_resp = Mock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": 1,
            "name": "hashgrid",
            "full_name": "xvantz/hashgrid",
            "owner": {"login": "xvantz"},
            "clone_url": "http://localhost:2000/xvantz/hashgrid.git",
            "mirror": False,
            "empty": False,
            "private": True,
            "description": "Spatial engine",
        }

        with patch.object(client._client, "get", return_value=mock_resp):
            repo = client.get_repo("xvantz", "hashgrid")

        assert repo.name == "hashgrid"
        assert repo.owner == "xvantz"

    def test_repo_exists_true(self) -> None:
        client = ForgejoClient("http://localhost:2000", "token")
        mock_resp = Mock(spec=httpx.Response)
        mock_resp.status_code = 200

        with patch.object(client._client, "get", return_value=mock_resp):
            assert client.repo_exists("xvantz", "hashgrid") is True

    def test_repo_exists_false(self) -> None:
        client = ForgejoClient("http://localhost:2000", "token")
        mock_resp = Mock(spec=httpx.Response)
        mock_resp.status_code = 404

        with patch.object(client._client, "get", return_value=mock_resp):
            assert client.repo_exists("xvantz", "nonexistent") is False

    def test_create_repo(self) -> None:
        client = ForgejoClient("http://localhost:2000", "token")
        mock_resp = Mock(spec=httpx.Response)
        mock_resp.status_code = 201
        mock_resp.json.return_value = {
            "id": 10,
            "name": "new-project",
            "full_name": "xvantz/new-project",
            "owner": {"login": "xvantz"},
            "clone_url": "http://localhost:2000/xvantz/new-project.git",
            "mirror": False,
            "empty": True,
            "private": True,
            "description": "A new project",
        }

        with patch.object(client._client, "post", return_value=mock_resp) as mock_post:
            repo = client.create_repo("new-project", description="A new project")

        mock_post.assert_called_once_with(
            "/api/v1/user/repos",
            json={
                "name": "new-project",
                "private": True,
                "description": "A new project",
                "auto_init": False,
            },
        )
        assert repo.name == "new-project"
        assert repo.owner == "xvantz"

    def test_migrate_repo(self) -> None:
        client = ForgejoClient("http://localhost:2000", "token")
        mock_resp = Mock(spec=httpx.Response)
        mock_resp.status_code = 201
        mock_resp.json.return_value = {
            "id": 11,
            "name": "external-repo",
            "full_name": "xvantz/external-repo",
            "owner": {"login": "xvantz"},
            "clone_url": "http://localhost:2000/xvantz/external-repo.git",
            "mirror": True,
            "empty": False,
            "private": True,
            "description": "Imported repo",
        }

        with patch.object(client._client, "post", return_value=mock_resp) as mock_post:
            repo = client.migrate_repo(
                "https://github.com/other/external-repo.git",
                "external-repo",
                mirror=True,
            )

        mock_post.assert_called_once_with(
            "/api/v1/repos/migrate",
            json={
                "clone_addr": "https://github.com/other/external-repo.git",
                "repo_name": "external-repo",
                "mirror": True,
                "private": True,
                "description": "",
            },
        )
        assert repo.mirror is True

    def test_add_push_mirror(self) -> None:
        client = ForgejoClient("http://localhost:2000", "token")
        mock_resp = Mock(spec=httpx.Response)
        mock_resp.status_code = 201
        mock_resp.json.return_value = {
            "remote_name": "github",
            "remote_address": "git@github.com:xvantz/repo.git",
        }

        with patch.object(client._client, "post", return_value=mock_resp) as mock_post:
            result = client.add_push_mirror(
                "xvantz", "hashgrid", "git@github.com:xvantz/hashgrid.git"
            )

        mock_post.assert_called_once_with(
            "/api/v1/repos/xvantz/hashgrid/push_mirrors",
            json={"remote_address": "git@github.com:xvantz/hashgrid.git"},
        )
        assert result["remote_name"] == "github"

    def test_list_push_mirrors(self, push_mirror_list: list[dict[str, Any]]) -> None:
        client = ForgejoClient("http://localhost:2000", "token")
        mock_resp = Mock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = push_mirror_list

        with patch.object(client._client, "get", return_value=mock_resp):
            mirrors = client.list_push_mirrors("xvantz", "hashgrid")

        assert len(mirrors) == 1
        assert mirrors[0]["remote_name"] == "github"

    def test_list_orgs(self) -> None:
        client = ForgejoClient("http://localhost:2000", "token")
        mock_resp = Mock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"id": 1, "login": "my-org"}]

        with patch.object(client._client, "get", return_value=mock_resp):
            orgs = client.list_orgs()

        assert len(orgs) == 1
        assert orgs[0]["login"] == "my-org"


class TestForgejoRepo:
    def test_parse(self, forgejo_repos: list[dict[str, Any]]) -> None:
        repo = ForgejoRepo(
            id=1,
            name="hashgrid",
            full_name="xvantz/hashgrid",
            owner="xvantz",
            clone_url="http://localhost:2000/xvantz/hashgrid.git",
            mirror=False,
            empty=False,
            private=True,
            description="Spatial engine",
        )

        assert repo.name == "hashgrid"
        assert repo.owner == "xvantz"
        assert repo.full_name == "xvantz/hashgrid"
        assert repo.mirror is False

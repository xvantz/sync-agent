"""Forgejo API client — thin wrapper around the Gitea/Forgejo REST API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class ForgejoRepo:
    id: int
    name: str
    full_name: str
    owner: str
    clone_url: str
    mirror: bool
    empty: bool
    private: bool
    description: str


class ForgejoClient:
    """HTTP client for the Forgejo API (Gitea-compatible)."""

    def __init__(self, base_url: str, token: str | None = None):
        self.base_url = base_url.rstrip("/")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"token {token}"
        self._client = httpx.Client(base_url=self.base_url, headers=headers)

    # ── repos ────────────────────────────────────────────────────────

    def list_repos(self, user: str | None = None) -> list[ForgejoRepo]:
        """List all repos accessible to the authenticated user."""
        if user:
            resp = self._get(f"/api/v1/users/{user}/repos")
        else:
            resp = self._get("/api/v1/user/repos")
        return [_parse_repo(r) for r in resp]

    def get_repo(self, owner: str, repo: str) -> ForgejoRepo:
        resp = self._get(f"/api/v1/repos/{owner}/{repo}")
        return _parse_repo(resp)

    def repo_exists(self, owner: str, repo: str) -> bool:
        resp = self._client.get(f"/api/v1/repos/{owner}/{repo}")
        return resp.status_code == 200

    def create_repo(
        self,
        name: str,
        *,
        private: bool = True,
        description: str = "",
        auto_init: bool = False,
    ) -> ForgejoRepo:
        """Create a new repository in Forgejo."""
        payload: dict[str, Any] = {
            "name": name,
            "private": private,
            "description": description,
            "auto_init": auto_init,
        }
        resp = self._post("/api/v1/user/repos", json=payload)
        return _parse_repo(resp)

    # ── migration (Pull Mirror import) ──────────────────────────────

    def migrate_repo(
        self,
        clone_addr: str,
        repo_name: str,
        *,
        mirror: bool = True,
        private: bool = True,
        description: str = "",
        auth_token: str | None = None,
    ) -> ForgejoRepo:
        """Migrate a repository from an external URL into Forgejo."""
        payload: dict[str, Any] = {
            "clone_addr": clone_addr,
            "repo_name": repo_name,
            "mirror": mirror,
            "private": private,
            "description": description,
        }
        if auth_token:
            payload["auth_token"] = auth_token
        resp = self._post("/api/v1/repos/migrate", json=payload)
        return _parse_repo(resp)

    # ── push mirrors ─────────────────────────────────────────────────

    def list_push_mirrors(self, owner: str, repo: str) -> list[dict]:
        resp = self._get(f"/api/v1/repos/{owner}/{repo}/push_mirrors")
        return resp  # list of {remote_name, remote_address, interval, ...}

    def add_push_mirror(
        self, owner: str, repo: str, remote_address: str
    ) -> dict:
        """Add a push mirror to a repository."""
        payload = {"remote_address": remote_address}
        resp = self._post(
            f"/api/v1/repos/{owner}/{repo}/push_mirrors", json=payload
        )
        return resp

    def remove_push_mirror(
        self, owner: str, repo: str, mirror_name: str
    ) -> None:
        self._delete(
            f"/api/v1/repos/{owner}/{repo}/push_mirrors/{mirror_name}"
        )

    # ── webhook management ──────────────────────────────────────────

    def list_webhooks(self, owner: str, repo: str) -> list[dict]:
        return self._get(f"/api/v1/repos/{owner}/{repo}/hooks")

    def create_webhook(
        self,
        owner: str,
        repo: str,
        url: str,
        events: list[str],
        *,
        secret: str = "",
    ) -> dict:
        payload = {
            "type": "forgejo",
            "url": url,
            "events": events,
            "secret": secret,
            "active": True,
        }
        return self._post(
            f"/api/v1/repos/{owner}/{repo}/hooks", json=payload
        )

    # ── user / org info ──────────────────────────────────────────────

    def get_authenticated_user(self) -> dict:
        return self._get("/api/v1/user")

    def list_orgs(self) -> list[dict]:
        return self._get("/api/v1/user/orgs")

    def list_org_repos(self, org_name: str) -> list[ForgejoRepo]:
        resp = self._get(f"/api/v1/orgs/{org_name}/repos")
        return [_parse_repo(r) for r in resp]

    # ── internals ────────────────────────────────────────────────────

    def _get(self, path: str) -> Any:
        resp = self._client.get(path)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, json: dict | None = None) -> Any:
        resp = self._client.post(path, json=json)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str) -> None:
        resp = self._client.delete(path)
        resp.raise_for_status()

    def close(self) -> None:
        self._client.close()


def _parse_repo(data: dict) -> ForgejoRepo:
    owner = data.get("owner", {}).get("login", "")
    if not owner and "full_name" in data:
        owner = data["full_name"].split("/")[0]
    return ForgejoRepo(
        id=data["id"],
        name=data["name"],
        full_name=data.get("full_name", f"{owner}/{data['name']}"),
        owner=owner,
        clone_url=data.get("clone_url", ""),
        mirror=data.get("mirror", False),
        empty=data.get("empty", False),
        private=data.get("private", True),
        description=data.get("description", ""),
    )

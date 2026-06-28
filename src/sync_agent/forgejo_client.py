"""Forgejo API client — thin wrapper around the Gitea/Forgejo REST API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sync_agent.retry import AsyncRetryClient


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
    """HTTP client for the Forgejo API (Gitea-compatible) with retry logic."""

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        max_attempts: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self._client = AsyncRetryClient(
            base_url=self.base_url,
            token=token,
            max_attempts=max_attempts,
        )

    # ── repos ────────────────────────────────────────────────────────

    def list_repos(self, user: str | None = None) -> list[ForgejoRepo]:
        """List all repos accessible to the authenticated user."""
        if user:
            resp = self._client.get(f"/api/v1/users/{user}/repos")
        else:
            resp = self._client.get("/api/v1/user/repos")
        return [_parse_repo(r) for r in resp]

    def get_repo(self, owner: str, repo: str) -> ForgejoRepo:
        resp = self._client.get(f"/api/v1/repos/{owner}/{repo}")
        return _parse_repo(resp)

    def repo_exists(self, owner: str, repo: str) -> bool:
        try:
            self._client.get(f"/api/v1/repos/{owner}/{repo}")
            return True
        except Exception:
            return False

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
        resp = self._client.post("/api/v1/user/repos", json=payload)
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
        resp = self._client.post("/api/v1/repos/migrate", json=payload)
        return _parse_repo(resp)

    # ── push mirrors ─────────────────────────────────────────────────

    def list_push_mirrors(self, owner: str, repo: str) -> list[dict]:
        return self._client.get(
            f"/api/v1/repos/{owner}/{repo}/push_mirrors"
        )

    def add_push_mirror(
        self, owner: str, repo: str, remote_address: str,
        interval: str = "8h0m0s",
    ) -> dict:
        """Add a push mirror to a repository."""
        payload = {"remote_address": remote_address, "interval": interval}
        return self._client.post(
            f"/api/v1/repos/{owner}/{repo}/push_mirrors", json=payload
        )

    def remove_push_mirror(
        self, owner: str, repo: str, mirror_name: str
    ) -> None:
        self._client.delete(
            f"/api/v1/repos/{owner}/{repo}/push_mirrors/{mirror_name}"
        )

    # ── webhook management ──────────────────────────────────────────

    def list_webhooks(self, owner: str, repo: str) -> list[dict]:
        return self._client.get(f"/api/v1/repos/{owner}/{repo}/hooks")

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
        return self._client.post(
            f"/api/v1/repos/{owner}/{repo}/hooks", json=payload
        )

    # ── user / org info ──────────────────────────────────────────────

    def get_authenticated_user(self) -> dict:
        return self._client.get("/api/v1/user")

    def list_orgs(self) -> list[dict]:
        return self._client.get("/api/v1/user/orgs")

    def list_org_repos(self, org_name: str) -> list[ForgejoRepo]:
        resp = self._client.get(f"/api/v1/orgs/{org_name}/repos")
        return [_parse_repo(r) for r in resp]

    # ── lifecycle ─────────────────────────────────────────────────

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

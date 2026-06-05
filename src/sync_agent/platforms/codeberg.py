"""Codeberg provider — uses Gitea API (same as Forgejo)."""

from __future__ import annotations

from typing import Any

import httpx

from sync_agent.platforms.base import PlatformProvider, PlatformRepo


class CodebergProvider(PlatformProvider):
    """Provider for codeberg.org."""

    name = "codeberg"

    def __init__(self, token: str):
        self._client = httpx.Client(
            base_url="https://codeberg.org/api/v1",
            headers={
                "Authorization": f"token {token}",
                "Content-Type": "application/json",
            },
        )

    def list_repos(self) -> list[PlatformRepo]:
        repos: list[PlatformRepo] = []
        # Personal repos
        repos.extend(self._fetch_repos("/user/repos"))
        # Organisation repos
        orgs = self._client.get("/user/orgs").json()
        for org in orgs:
            org_repos = self._fetch_repos(f"/orgs/{org['login']}/repos")
            repos.extend(org_repos)
        return repos

    def create_repo(
        self, name: str, *, private: bool = True, description: str = ""
    ) -> PlatformRepo:
        payload: dict[str, Any] = {
            "name": name,
            "private": private,
            "description": description,
            "auto_init": False,
        }
        resp = self._client.post("/user/repos", json=payload)
        resp.raise_for_status()
        return self._parse_repo(resp.json())

    def repo_exists(self, name: str, owner: str | None = None) -> bool:
        if not owner:
            # Fallback: list and check
            repos = self.list_repos()
            return any(r.name == name for r in repos)
        resp = self._client.get(f"/repos/{owner}/{name}")
        return resp.status_code == 200

    def ssh_push_url(self, repo: PlatformRepo) -> str:
        return f"git@codeberg.org:{repo.owner}/{repo.name}.git"

    # ── helpers ──────────────────────────────────────────────────────

    def _fetch_repos(self, path: str) -> list[PlatformRepo]:
        repos: list[PlatformRepo] = []
        page = 1
        while True:
            resp = self._client.get(
                path, params={"page": page, "limit": 50}
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            for r in data:
                repos.append(self._parse_repo(r))
            page += 1
        return repos

    @staticmethod
    def _parse_repo(data: dict) -> PlatformRepo:
        owner = data.get("owner", {}).get("login", "")
        return PlatformRepo(
            name=data["name"],
            owner=owner,
            clone_url=data.get("clone_url", ""),
            private=data.get("private", True),
            description=data.get("description", ""),
            platform="codeberg",
        )

    def close(self) -> None:
        self._client.close()

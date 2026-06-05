"""GitHub platform provider."""

from __future__ import annotations

from typing import Any

import httpx

from sync_agent.platforms.base import PlatformProvider, PlatformRepo


class GitHubProvider(PlatformProvider):
    """Provider for github.com."""

    name = "github"

    def __init__(self, token: str):
        self._client = httpx.Client(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "sync-agent/0.1",
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
        data = resp.json()
        return self._parse_repo(data)

    def repo_exists(self, name: str, owner: str | None = None) -> bool:
        if owner:
            resp = self._client.get(f"/repos/{owner}/{name}")
        else:
            # Search for it
            resp = self._client.get(
                "/search/repositories",
                params={"q": f"{name} in:name fork:true"},
            )
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                return any(r["name"] == name for r in items)
            return False
        return resp.status_code == 200

    def ssh_push_url(self, repo: PlatformRepo) -> str:
        return f"git@github.com:{repo.owner}/{repo.name}.git"

    # ── helpers ──────────────────────────────────────────────────────

    def _fetch_repos(self, path: str) -> list[PlatformRepo]:
        repos: list[PlatformRepo] = []
        page = 1
        while True:
            resp = self._client.get(path, params={"page": page, "per_page": 100})
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
        return PlatformRepo(
            name=data["name"],
            owner=data["owner"]["login"],
            clone_url=data["clone_url"],
            private=data.get("private", True),
            description=data.get("description", ""),
            platform="github",
        )

    def close(self) -> None:
        self._client.close()

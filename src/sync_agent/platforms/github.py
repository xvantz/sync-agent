"""GitHub platform provider."""

from __future__ import annotations

from typing import Any

from sync_agent.platforms.base import PlatformProvider, PlatformRepo
from sync_agent.retry import AsyncRetryClient


class GitHubProvider(PlatformProvider):
    """Provider for github.com with automatic retry."""

    name = "github"

    def __init__(self, token: str, *, max_attempts: int = 3):
        self._client = AsyncRetryClient(
            base_url="https://api.github.com",
            token=token,
            max_attempts=max_attempts,
        )

    def list_repos(self) -> list[PlatformRepo]:
        repos: list[PlatformRepo] = []
        # Personal repos
        repos.extend(self._fetch_repos("/user/repos"))
        # Organisation repos
        orgs = self._client.get("/user/orgs")
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
        data = self._client.post("/user/repos", json=payload)
        return self._parse_repo(data)

    def repo_exists(self, name: str, owner: str | None = None) -> bool:
        if owner:
            try:
                self._client.get(f"/repos/{owner}/{name}")
                return True
            except Exception:
                return False
        # Search fallback
        try:
            data = self._client.get(
                "/search/repositories",
                params={"q": f"{name} in:name fork:true"},
            )
            items = data.get("items", [])
            return any(r["name"] == name for r in items)
        except Exception:
            return False

    def ssh_push_url(self, repo: PlatformRepo) -> str:
        return f"git@github.com:{repo.owner}/{repo.name}.git"

    # ── helpers ──────────────────────────────────────────────────────

    def _fetch_repos(self, path: str) -> list[PlatformRepo]:
        repos: list[PlatformRepo] = []
        page = 1
        while True:
            data = self._client.get(
                path, params={"page": page, "per_page": 100}
            )
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

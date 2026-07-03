"""GitLab platform provider with retry."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from sync_agent.platforms.base import PlatformProvider, PlatformRepo
from sync_agent.retry import AsyncRetryClient


class GitLabProvider(PlatformProvider):
    """Provider for gitlab.com with automatic retry."""

    name = "gitlab"

    def __init__(self, token: str, *, max_attempts: int = 3):
        self._client = AsyncRetryClient(
            base_url="https://gitlab.com/api/v4",
            token=token,
            max_attempts=max_attempts,
        )

    def list_repos(self) -> list[PlatformRepo]:
        repos: list[PlatformRepo] = []
        repos.extend(self._fetch_repos("/projects", {"owned": "true"}))
        groups = self._client.get("/groups")
        for group in groups:
            group_repos = self._fetch_repos(
                f"/groups/{group['id']}/projects"
            )
            repos.extend(group_repos)
        return repos

    def create_repo(
        self, name: str, *, private: bool = True, description: str = ""
    ) -> PlatformRepo:
        payload: dict[str, Any] = {
            "name": name,
            "visibility": "private" if private else "public",
            "description": description,
        }
        data = self._client.post("/projects", json=payload)
        return self._parse_repo(data)

    def repo_exists(self, name: str, owner: str | None = None) -> bool:
        params: dict[str, str] = {"search": name}
        if owner:
            pass  # GitLab search works globally within user scope
        params["owned"] = "true"
        try:
            data = self._client.get("/projects", params=params)
            return any(p["path"] == name for p in data)
        except Exception:
            return False

    def delete_repo(self, owner: str, name: str) -> bool:
        """Delete a repository from GitLab."""
        encoded = quote(f"{owner}/{name}", safe="")
        try:
            self._client.delete(f"/projects/{encoded}")
            return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return False
            raise

    def ssh_push_url(self, repo: PlatformRepo) -> str:
        return f"git@gitlab.com:{repo.owner}/{repo.name}.git"

    # ── helpers ──────────────────────────────────────────────────────

    def _fetch_repos(
        self, path: str, extra_params: dict[str, str] | None = None
    ) -> list[PlatformRepo]:
        repos: list[PlatformRepo] = []
        page = 1
        params = {"per_page": "100", **(extra_params or {})}
        while True:
            data = self._client.get(
                path, params={**params, "page": str(page)}
            )
            if not data:
                break
            for r in data:
                repos.append(self._parse_repo(r))
            page += 1
        return repos

    @staticmethod
    def _parse_repo(data: dict) -> PlatformRepo:
        owner = data.get("namespace", {}).get("path", "")
        return PlatformRepo(
            name=data["path"],
            owner=owner,
            clone_url=data.get("http_url_to_repo", ""),
            private=not data.get("visibility", "").startswith("public"),
            description=data.get("description", ""),
            platform="gitlab",
        )

    def close(self) -> None:
        self._client.close()

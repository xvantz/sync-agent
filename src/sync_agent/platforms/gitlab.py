"""GitLab platform provider."""

from __future__ import annotations

from typing import Any

import httpx

from sync_agent.platforms.base import PlatformProvider, PlatformRepo


class GitLabProvider(PlatformProvider):
    """Provider for gitlab.com."""

    name = "gitlab"

    def __init__(self, token: str):
        self._client = httpx.Client(
            base_url="https://gitlab.com/api/v4",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )

    def list_repos(self) -> list[PlatformRepo]:
        repos: list[PlatformRepo] = []

        # Owned projects
        repos.extend(self._fetch_repos("/projects", {"owned": "true"}))

        # Group (organisation) projects
        groups = self._client.get("/groups").json()
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
        resp = self._client.post("/projects", json=payload)
        resp.raise_for_status()
        return self._parse_repo(resp.json())

    def repo_exists(self, name: str, owner: str | None = None) -> bool:
        if owner:
            resp = self._client.get(
                "/projects", params={"search": name}
            )
            if resp.status_code == 200:
                projects = resp.json()
                return any(p["path"] == name for p in projects)
            return False
        resp = self._client.get(
            "/projects", params={"search": name, "owned": "true"}
        )
        if resp.status_code == 200:
            projects = resp.json()
            return any(p["path"] == name for p in projects)
        return False

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
            resp = self._client.get(path, params={**params, "page": str(page)})
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

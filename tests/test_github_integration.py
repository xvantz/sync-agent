"""Integration tests against real GitHub API (read-only).

Requires GITHUB_TOKEN env var or a token in ~/.git-credentials.
Skips automatically if no token is available.
"""

from __future__ import annotations

import os
import re

import pytest

from sync_agent.platforms.github import GitHubProvider

pytestmark = pytest.mark.integration


def _get_github_token() -> str | None:
    """Try to get a GitHub token from env or ~/.git-credentials."""
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    try:
        with open(os.path.expanduser("~/.git-credentials")) as f:
            m = re.match(
                r"https://[^:]+:([^@]+)@github\.com", f.read().strip()
            )
            if m:
                return m.group(1)
    except (FileNotFoundError, OSError):
        pass
    return None


@pytest.fixture(scope="module")
def github_token() -> str | None:
    return _get_github_token()


class TestGitHubProviderIntegration:
    """Real integration tests against github.com API."""

    def test_list_repos(self, github_token: str | None) -> None:
        """Should list real repos from the authenticated user."""
        if not github_token:
            pytest.skip("No GitHub token available")

        provider = GitHubProvider(github_token)
        try:
            repos = provider.list_repos()
            assert len(repos) > 0, "Expected at least one repo"
            # All should be valid PlatformRepo objects
            for repo in repos:
                assert repo.name, f"Repo missing name: {repo}"
                assert repo.owner, f"Repo missing owner: {repo}"
                assert repo.clone_url, f"Repo missing clone_url: {repo}"
                assert repo.platform == "github"

            # Log what we found
            names = [r.name for r in repos]
            print(f"\n  Found {len(repos)} repos: {', '.join(names[:10])}")
            if len(repos) > 10:
                print(f"  ... and {len(repos) - 10} more")
        finally:
            provider.close()

    def test_repo_exists(self, github_token: str | None) -> None:
        """Known repo should exist."""
        if not github_token:
            pytest.skip("No GitHub token available")

        provider = GitHubProvider(github_token)
        try:
            # Find the first repo to check
            repos = provider.list_repos()
            if not repos:
                pytest.skip("No repos to test against")

            first_repo = repos[0]
            exists = provider.repo_exists(
                first_repo.name, first_repo.owner
            )
            assert exists is True, (
                f"Repo {first_repo.owner}/{first_repo.name} should exist"
            )
        finally:
            provider.close()

    def test_nonexistent_repo_does_not_exist(
        self, github_token: str | None
    ) -> None:
        """Random repo should not exist under this user."""
        if not github_token:
            pytest.skip("No GitHub token available")

        provider = GitHubProvider(github_token)
        try:
            exists = provider.repo_exists(
                "this-repo-definitely-does-not-exist-12345", "xvantz"
            )
            assert exists is False
        finally:
            provider.close()

    def test_rate_limit_available(self, github_token: str | None) -> None:
        """API rate limit should be visible and reasonable."""
        import httpx

        if not github_token:
            pytest.skip("No GitHub token available")

        resp = httpx.get(
            "https://api.github.com/rate_limit",
            headers={
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "sync-agent-test/0.1",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        core = data.get("rate", {})
        remaining = core.get("remaining", 0)
        limit = core.get("limit", 0)
        print(f"\n  Rate limit: {remaining}/{limit}")
        assert limit > 0, "Rate limit should be > 0"

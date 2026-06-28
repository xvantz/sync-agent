"""Pusher — adds Push Mirrors on Forgejo repos → cloud platforms."""

from __future__ import annotations

import logging

from sync_agent.forgejo_client import ForgejoClient
from sync_agent.platforms.base import PlatformProvider
from sync_agent.reconciler import DiffResult

logger = logging.getLogger(__name__)


class Pusher:
    """Set up Push Mirrors from Forgejo repositories to cloud platforms."""

    def __init__(
        self,
        forgejo: ForgejoClient,
        platforms: dict[str, PlatformProvider],
    ):
        self._forgejo = forgejo
        self._platforms = platforms

    def _get_platform_token(self, name: str) -> str | None:
        """Get auth token from a platform provider."""
        provider = self._platforms.get(name)
        if not provider:
            return None
        client = getattr(provider, "_client", None)
        return client._token if hasattr(client, "_token") else None

    def _build_push_url(self, target: str, owner: str, repo: str) -> str:
        """Build HTTPS push URL with token for authentication."""
        token = self._get_platform_token(target)
        if token:
            return f"https://{token}@github.com/{owner}/{repo}.git"
        # Fallback to SSH if no token available
        return f"git@{target}.com:{owner}/{repo}.git"

    def run(
        self,
        diff: DiffResult,
        *,
        dry_run: bool = False,
    ) -> int:
        """Set up Push Mirrors for repos that are missing them.

        Args:
            diff: The diff result (uses missing_push_mirrors list).
            dry_run: If True, only log.

        Returns:
            Number of push mirrors set up.
        """
        count = 0
        for fj_repo, missing_targets in diff.missing_push_mirrors:
            for target in missing_targets:
                provider = self._platforms.get(target)
                if not provider:
                    logger.warning("No provider for target '%s'", target)
                    continue

                remote_url = self._build_push_url(
                    target, fj_repo.owner, fj_repo.name
                )

                logger.info(
                    "%s Add push mirror %s -> %s",
                    "[DRY-RUN]" if dry_run else "",
                    fj_repo.full_name,
                    target,
                )

                if dry_run:
                    count += 1
                    continue

                try:
                    self._forgejo.add_push_mirror(
                        fj_repo.owner, fj_repo.name, remote_url
                    )
                    logger.info("  ✓ Push mirror added to %s", target)
                    count += 1
                except Exception as e:
                    logger.error(
                        "  ✗ Failed to add push mirror to %s: %s",
                        target,
                        e,
                    )

        return count

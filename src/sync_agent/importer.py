"""Importer — pulls missing repos from cloud platforms into Forgejo."""

from __future__ import annotations

import logging

from sync_agent.forgejo_client import ForgejoClient
from sync_agent.platforms.base import PlatformProvider, PlatformRepo
from sync_agent.reconciler import DiffResult

logger = logging.getLogger(__name__)


class Importer:
    """Import missing repos from cloud platforms into Forgejo as Pull Mirrors."""

    def __init__(
        self,
        forgejo: ForgejoClient,
        platforms: dict[str, PlatformProvider],
    ):
        self._forgejo = forgejo
        self._platforms = platforms

    def run(
        self,
        diff: DiffResult,
        *,
        dry_run: bool = False,
    ) -> int:
        """Import all repos that are missing in Forgejo.

        Args:
            diff: The diff result from Reconciler.
            dry_run: If True, only log what would be done.

        Returns:
            Number of imported repos.
        """
        count = 0
        for platform_name, cloud_repo in diff.missing_in_forgejo:
            provider = self._platforms.get(platform_name)
            if not provider:
                logger.warning("No provider for platform '%s'", platform_name)
                continue

            # Determine the auth token for the source platform
            # For public repos, no token needed. For private, we need one.
            clone_url = cloud_repo.clone_url

            logger.info(
                "%s Import %s from %s (owner=%s)",
                "[DRY-RUN]" if dry_run else "",
                cloud_repo.name,
                platform_name,
                cloud_repo.owner,
            )

            if dry_run:
                count += 1
                continue

            try:
                result = self._forgejo.migrate_repo(
                    clone_addr=clone_url,
                    repo_name=cloud_repo.name,
                    mirror=True,
                    private=cloud_repo.private,
                    description=cloud_repo.description,
                )
                logger.info(
                    "  → Imported %s as %s (id=%d)",
                    result.name,
                    "mirror" if result.mirror else "clone",
                    result.id,
                )
                count += 1
            except Exception as e:
                logger.error(
                    "  ✗ Failed to import %s: %s", cloud_repo.name, e
                )

        return count

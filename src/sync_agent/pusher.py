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
        """Build SSH push URL (HTTPS with token not supported by Forgejo security check)."""
        return f"git@{target}.com:{owner}/{repo}.git"

    def _ensure_repo_exists(
        self,
        provider: PlatformProvider,
        name: str,
        owner: str,
        *,
        private: bool = True,
        description: str = "",
    ) -> bool:
        """Create repo on target platform if it doesn't exist yet.

        Returns True if repo was created, False if it already existed.
        """
        try:
            exists = provider.repo_exists(name, owner=owner)
        except Exception:
            exists = False

        if exists:
            return False

        logger.info("    Repo '%s/%s' missing on %s, creating...", owner, name, provider.name)
        try:
            provider.create_repo(name, private=private, description=description)
            return True
        except Exception as e:
            logger.error("    Could not create repo on %s: %s", provider.name, e)
            return False

    def run(
        self,
        diff: DiffResult,
        *,
        dry_run: bool = False,
    ) -> int:
        """Set up Push Mirrors for repos that are missing them.

        Creates repos on target platforms first if they don't exist,
        then adds push mirrors.

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

                logger.info(
                    "%s Process push mirror %s -> %s",
                    "[DRY-RUN]" if dry_run else "",
                    fj_repo.full_name,
                    target,
                )

                if not dry_run:
                    # Create repo on target platform if missing
                    self._ensure_repo_exists(
                        provider,
                        fj_repo.name,
                        fj_repo.owner,
                        private=fj_repo.private,
                        description=fj_repo.description,
                    )

                remote_url = self._build_push_url(
                    target, fj_repo.owner, fj_repo.name
                )

                if dry_run:
                    count += 1
                    continue

                try:
                    mirror = self._forgejo.add_push_mirror(
                        fj_repo.owner, fj_repo.name, remote_url
                    )
                    logger.info("  ✓ Push mirror added to %s", target)

                    # Force immediate sync so existing code is pushed
                    mirror_name = mirror.get("remote_name", "")
                    if mirror_name:
                        try:
                            self._forgejo.sync_push_mirror(
                                fj_repo.owner, fj_repo.name, mirror_name
                            )
                            logger.info(
                                "  ✓ Forced initial sync for %s", target
                            )
                        except Exception as sync_err:
                            logger.warning(
                                "  ⚠ Initial sync trigger failed: %s",
                                sync_err,
                            )
                    count += 1
                except Exception as e:
                    logger.error(
                        "  ✗ Failed to add push mirror to %s: %s",
                        target,
                        e,
                    )

        return count

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
        """Ensure the repo exists on the target platform.

        Returns True if the repo is ready (already exists or was just created).
        Returns False if creation was attempted but failed.
        """
        try:
            exists = provider.repo_exists(name, owner=owner)
        except Exception:
            exists = False

        if exists:
            logger.debug("  Repo '%s/%s' already exists on %s", owner, name, provider.name)
            return True  # Already exists → proceed

        logger.info("    Repo '%s/%s' missing on %s, creating...", owner, name, provider.name)
        try:
            provider.create_repo(name, private=private, description=description)
            return True  # Created successfully → proceed
        except Exception as e:
            logger.error("    Could not create repo on %s: %s", provider.name, e)
            return False  # Failed → skip push mirror

    def sync_all_mirrors(
        self,
        *,
        dry_run: bool = False,
    ) -> int:
        """Trigger an immediate sync on ALL existing push mirrors.

        Calls the sync endpoint ONCE per repo (it syncs all mirrors for that repo).

        This ensures code is pushed now rather than waiting for the
        periodic sync interval (default 8h).

        Args:
            dry_run: If True, only log what would be synced.

        Returns:
            Number of repos synced.
        """
        repos = self._forgejo.list_repos()
        count = 0
        for repo in repos:
            try:
                mirrors = self._forgejo.list_push_mirrors(
                    repo.owner, repo.name
                )
            except Exception:
                continue
            if not mirrors:
                continue
            # Sync once per repo — one call syncs ALL mirrors for it
            remote = mirrors[0].get("remote_address", "?")
            if dry_run:
                logger.info("  [DRY-RUN] Would sync %s → %s", repo.full_name, remote)
                count += 1
                continue
            try:
                self._forgejo.sync_push_mirror(
                    repo.owner, repo.name, mirrors[0].get("remote_name")
                )
                logger.info("  ✓ Synced %s", repo.full_name)
                count += 1
            except Exception as e:
                logger.warning(
                    "  ⚠ Sync trigger failed for %s: %s",
                    repo.full_name, e,
                )
        return count

    def run(
        self,
        diff: DiffResult,
        *,
        dry_run: bool = False,
        sync_all: bool = False,
    ) -> int:
        """Set up Push Mirrors for repos that are missing them.

        Creates repos on target platforms first if they don't exist,
        then adds push mirrors. After setting up new mirrors, triggers
        an immediate sync on ALL existing mirrors.

        Args:
            diff: The diff result (uses missing_push_mirrors list).
            dry_run: If True, only log.
            sync_all: If True (default), sync all mirrors after setup.

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
                    if not self._ensure_repo_exists(
                        provider,
                        fj_repo.name,
                        fj_repo.owner,
                        private=fj_repo.private,
                        description=fj_repo.description,
                    ):
                        logger.warning(
                            "  ✗ Skipping push mirror for %s — cannot create repo '%s/%s' on %s",
                            fj_repo.full_name, fj_repo.owner, fj_repo.name, target,
                        )
                        continue

                remote_url = self._build_push_url(
                    target, fj_repo.owner, fj_repo.name
                )

                if dry_run:
                    count += 1
                    continue

                # Remove existing broken/stale mirrors to this target before adding new one
                try:
                    existing = self._forgejo.list_push_mirrors(
                        fj_repo.owner, fj_repo.name
                    )
                    for m in existing:
                        if target in m.get("remote_address", ""):
                            err = m.get("last_error", "")
                            soc = m.get("sync_on_commit", False)
                            if (
                                (err and "Repository not found" in err)
                                or not soc
                            ):
                                if err and "Repository not found" in err:
                                    reason = "broken (target repo missing)"
                                else:
                                    reason = "stale (sync_on_commit=False)"
                                logger.info(
                                    "  Removing %s push mirror for %s",
                                    reason, target,
                                )
                                self._forgejo.remove_push_mirror(
                                    fj_repo.owner,
                                    fj_repo.name,
                                    m["remote_name"],
                                )
                except Exception as list_err:
                    logger.debug(
                        "  Could not list/clean existing mirrors: %s",
                        list_err,
                    )

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

        # After setting up/checking mirrors, sync ALL existing ones
        # so code is pushed immediately instead of waiting for the periodic interval
        if not dry_run and sync_all:
            logger.info("Syncing all push mirrors...")
            synced = self.sync_all_mirrors()
            if synced:
                logger.info("Triggered sync for %d push mirrors", synced)

        return count

"""Reconciler — discover repos on all platforms and compute the diff."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sync_agent.forgejo_client import ForgejoClient, ForgejoRepo
from sync_agent.platforms.base import PlatformProvider, PlatformRepo

logger = logging.getLogger(__name__)


@dataclass
class DiffResult:
    """The difference between what's in Forgejo and what's in the clouds."""

    # Repos that exist on a cloud platform but NOT in Forgejo
    missing_in_forgejo: list[tuple[str, PlatformRepo]] = field(default_factory=list)
    # Repos that exist in Forgejo but have no Push Mirror to a target
    missing_push_mirrors: list[tuple[ForgejoRepo, list[str]]] = field(default_factory=list)
    # Total counts per platform
    platform_counts: dict[str, int] = field(default_factory=dict)


class Reconciler:
    """Compare repository lists between Forgejo and cloud platforms."""

    def __init__(
        self,
        forgejo: ForgejoClient,
        platforms: dict[str, PlatformProvider],
        forgejo_user: str = "",
    ):
        self._forgejo = forgejo
        self._platforms = platforms
        self._forgejo_user = forgejo_user

    def discover(self) -> DiffResult:
        """Fetch all repos from all sources and compute the diff."""
        # 1. Get all repos from Forgejo
        forgejo_repos = self._forgejo.list_repos(self._forgejo_user or None)
        forgejo_by_name: dict[str, ForgejoRepo] = {}
        for r in forgejo_repos:
            forgejo_by_name[r.name] = r

        result = DiffResult()

        # 2. For each cloud platform
        for platform_name, provider in self._platforms.items():
            cloud_repos = provider.list_repos()
            result.platform_counts[platform_name] = len(cloud_repos)

            for cloud_repo in cloud_repos:
                # Check if this repo exists in Forgejo
                if cloud_repo.name not in forgejo_by_name:
                    result.missing_in_forgejo.append((platform_name, cloud_repo))
                else:
                    fj_repo = forgejo_by_name[cloud_repo.name]
                    self._check_push_mirrors(fj_repo, platform_name, result)

        # 3. Also check push mirrors for Forgejo-only repos (not in cloud)
        for fj_repo in forgejo_repos:
            for platform_name in self._platforms:
                self._check_push_mirrors(fj_repo, platform_name, result)

        return result

    # ── helpers ──────────────────────────────────────────────────────

    def _check_push_mirrors(
        self,
        fj_repo: ForgejoRepo,
        target_platform: str,
        result: DiffResult,
    ) -> None:
        """If a repo lacks push mirror to target_platform, record it."""
        try:
            mirrors = self._forgejo.list_push_mirrors(
                fj_repo.owner, fj_repo.name
            )
        except Exception as e:
            logger.debug("Can't list mirrors for %s: %s", fj_repo.full_name, e)
            return

        has_target = any(
            target_platform in m.get("remote_address", "")
            for m in mirrors
        )
        logger.debug(
            "Push mirrors for %s: %d mirrors, has %s: %s",
            fj_repo.full_name,
            len(mirrors),
            target_platform,
            has_target,
        )
        if not has_target:
            # Find existing entry or create new one
            for i, (existing_repo, missing_targets) in enumerate(
                result.missing_push_mirrors
            ):
                if existing_repo.name == fj_repo.name:
                    result.missing_push_mirrors[i][1].append(target_platform)
                    return
            result.missing_push_mirrors.append((fj_repo, [target_platform]))

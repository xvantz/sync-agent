"""Abstract platform provider — interface for all Git forges."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PlatformRepo:
    """A repository as seen by a cloud platform."""

    name: str
    owner: str
    clone_url: str
    private: bool
    description: str
    platform: str  # "github" | "codeberg" | "gitlab"


class PlatformProvider(ABC):
    """Base class for platform-specific API clients."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Platform name: 'github', 'codeberg', 'gitlab'."""

    @abstractmethod
    def list_repos(self) -> list[PlatformRepo]:
        """List all repositories accessible to the authenticated user.

        Includes both personal and organisation repos where the user
        has access.
        """

    @abstractmethod
    def create_repo(
        self, name: str, *, private: bool = True, description: str = ""
    ) -> PlatformRepo:
        """Create a repository on this platform."""

    @abstractmethod
    def repo_exists(self, name: str, owner: str | None = None) -> bool:
        """Check if a repository already exists."""

    @abstractmethod
    def delete_repo(self, owner: str, name: str) -> bool:
        """Delete a repository from this platform.

        Args:
            owner: Repository owner (user or org).
            name: Repository name.

        Returns:
            True if deleted, False if it didn't exist.
        """

    def ssh_push_url(self, repo: PlatformRepo) -> str:
        """Return the SSH URL suitable for use as a push mirror target."""
        # Default: git@github.com:owner/repo.git
        return f"git@{self.name}.com:{repo.owner}/{repo.name}.git"

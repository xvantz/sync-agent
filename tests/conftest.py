"""Shared fixtures for sync-agent tests."""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from sync_agent.config import Config
from sync_agent.forgejo_client import ForgejoClient, ForgejoRepo


# ── sample data ─────────────────────────────────────────────────────

SAMPLE_CONFIG_YAML = """
forgejo:
  url: "http://localhost:2000"
  token: "${FORGEJO_TOKEN}"

platforms:
  github:
    token: "${GITHUB_TOKEN}"
  codeberg:
    token: "${CODEBERG_TOKEN}"

import:
  enabled: true
  organisations: ["my-org"]

push_mirrors:
  enabled: true
  targets:
    - github
    - codeberg

webhook:
  enabled: true
  host: "127.0.0.1"
  port: 9123
"""


@pytest.fixture
def sample_config_yaml() -> str:
    return SAMPLE_CONFIG_YAML


@pytest.fixture
def resolved_config_data() -> dict[str, Any]:
    """Config data after env var substitution (tokens replaced)."""
    return {
        "forgejo": {"url": "http://localhost:2000", "token": "fj-token"},
        "platforms": {
            "github": {"token": "gh-token"},
            "codeberg": {"token": "cb-token"},
        },
        "import": {"enabled": True, "organisations": ["my-org"]},
        "push_mirrors": {"enabled": True, "targets": ["github", "codeberg"]},
        "webhook": {"enabled": True, "host": "127.0.0.1", "port": 9123},
    }


@pytest.fixture
def config(resolved_config_data: dict[str, Any]) -> Config:
    return Config.from_dict(resolved_config_data)


# ── Forgejo fixtures ────────────────────────────────────────────────

@pytest.fixture
def forgejo_repos() -> list[dict[str, Any]]:
    return [
        {
            "id": 1,
            "name": "hashgrid",
            "full_name": "xvantz/hashgrid",
            "owner": {"login": "xvantz", "id": 100},
            "clone_url": "http://localhost:2000/xvantz/hashgrid.git",
            "mirror": False,
            "empty": False,
            "private": True,
            "description": "Spatial engine",
        },
        {
            "id": 2,
            "name": "coolcontrol",
            "full_name": "xvantz/coolcontrol",
            "owner": {"login": "xvantz", "id": 100},
            "clone_url": "http://localhost:2000/xvantz/coolcontrol.git",
            "mirror": True,
            "empty": False,
            "private": True,
            "description": "Fan control",
        },
    ]


@pytest.fixture
def push_mirror_list() -> list[dict[str, Any]]:
    return [
        {
            "remote_name": "github",
            "remote_address": "git@github.com:xvantz/hashgrid.git",
            "interval": "8h0m0s",
        }
    ]


@pytest.fixture
def forgejo_client() -> ForgejoClient:
    return ForgejoClient("http://localhost:2000", "test-token")


# ── Cloud platform fixtures ─────────────────────────────────────────

@pytest.fixture
def github_repos() -> list[dict[str, Any]]:
    return [
        {
            "name": "hashgrid",
            "full_name": "xvantz/hashgrid",
            "owner": {"login": "xvantz"},
            "clone_url": "https://github.com/xvantz/hashgrid.git",
            "private": True,
            "description": "Spatial engine",
        },
        {
            "name": "resume",
            "full_name": "xvantz/resume",
            "owner": {"login": "xvantz"},
            "clone_url": "https://github.com/xvantz/resume.git",
            "private": False,
            "description": "My resume",
        },
    ]


@pytest.fixture
def codeberg_repos() -> list[dict[str, Any]]:
    return [
        {
            "name": "dotfiles",
            "full_name": "xvantz/dotfiles",
            "owner": {"login": "xvantz"},
            "clone_url": "https://codeberg.org/xvantz/dotfiles.git",
            "private": False,
            "description": "NixOS dotfiles",
        },
    ]


# ── Respx / HTTP mock helpers ───────────────────────────────────────

@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set required env vars for tests that use Config.from_file."""
    monkeypatch.setenv("FORGEJO_TOKEN", "fj-token")
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
    monkeypatch.setenv("CODEBERG_TOKEN", "cb-token")
    monkeypatch.setenv("GITLAB_TOKEN", "gl-token")

"""Tests for config.py — YAML loading and env var substitution."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from sync_agent.config import Config


class TestConfigFromFile:
    def test_loads_yaml(self, tmp_path: Path, sample_config_yaml: str) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(sample_config_yaml)
        cfg = Config.from_file(config_file)
        assert cfg.forgejo_url == "http://localhost:2000"

    def test_env_var_substitution(
        self, tmp_path: Path, sample_config_yaml: str
    ) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(sample_config_yaml)
        os.environ["FORGEJO_TOKEN"] = "my-secret-token"
        os.environ["GITHUB_TOKEN"] = "gh-pat"
        os.environ["CODEBERG_TOKEN"] = "cb-token"
        try:
            cfg = Config.from_file(config_file)
            assert cfg.forgejo_token == "my-secret-token"
            assert cfg.platform_token("github") == "gh-pat"
            assert cfg.platform_token("codeberg") == "cb-token"
        finally:
            for k in ("FORGEJO_TOKEN", "GITHUB_TOKEN", "CODEBERG_TOKEN"):
                os.environ.pop(k, None)

    def test_missing_env_var_raises(
        self, tmp_path: Path, sample_config_yaml: str
    ) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(sample_config_yaml)
        os.environ.pop("FORGEJO_TOKEN", None)
        with pytest.raises(ValueError, match="FORGEJO_TOKEN"):
            Config.from_file(config_file)

    def test_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            Config.from_file("/nonexistent/config.yaml")


class TestConfigFromDict:
    def test_basic_properties(self, config: Config) -> None:
        assert config.forgejo_url == "http://localhost:2000"
        assert config.forgejo_token == "fj-token"

    def test_platform_tokens(self, config: Config) -> None:
        assert config.platform_token("github") == "gh-token"
        assert config.platform_token("codeberg") == "cb-token"

    def test_enabled_platforms(self, config: Config) -> None:
        platforms = config.enabled_platforms
        assert "github" in platforms
        assert "codeberg" in platforms
        assert "gitlab" not in platforms

    def test_import_settings(self, config: Config) -> None:
        assert config.import_enabled is True
        assert config.import_organisations == ["my-org"]

    def test_push_mirror_settings(self, config: Config) -> None:
        assert config.push_mirrors_enabled is True
        assert config.push_mirror_targets == ["github", "codeberg"]

    def test_webhook_settings(self, config: Config) -> None:
        assert config.webhook_enabled is True
        assert config.webhook_host == "127.0.0.1"
        assert config.webhook_port == 9123

    def test_defaults_when_missing(self) -> None:
        cfg = Config.from_dict({})
        assert cfg.forgejo_url == "http://localhost:2000"
        assert cfg.forgejo_token is None
        assert cfg.import_enabled is True
        assert cfg.import_organisations == []
        assert cfg.webhook_port == 9123
        assert cfg.enabled_platforms == []

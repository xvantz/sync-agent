"""Configuration loader with environment variable substitution."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml


_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def _substitute(value: str) -> str:
    """Replace ${VAR} with environment variable values."""

    def _replace(m: re.Match) -> str:
        var = m.group(1)
        val = os.environ.get(var)
        if val is None:
            raise ValueError(
                f"Environment variable '{var}' is required but not set"
            )
        return val

    return _ENV_VAR_RE.sub(_replace, value)


def _walk(obj: Any) -> Any:
    """Recursively walk a config tree and substitute env vars in strings."""
    if isinstance(obj, str):
        return _substitute(obj)
    if isinstance(obj, dict):
        return {k: _walk(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(item) for item in obj]
    return obj


class Config:
    """Immutable config object holding the entire sync-agent configuration."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._raw = data

    @classmethod
    def from_file(cls, path: str | Path) -> "Config":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        raw = yaml.safe_load(path.read_text())
        try:
            resolved = _walk(raw)
        except ValueError as e:
            raise ValueError(
                f"Config error in {path}: {e}\n"
                f"Hint: source the env file first or set the missing variable"
            ) from e
        return cls(resolved)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        try:
            resolved = _walk(data)
        except ValueError as e:
            raise ValueError(
                f"Config error: {e}\n"
                f"Hint: source the env file first or set the missing variable"
            ) from e
        return cls(resolved)

    # ── helpers ──────────────────────────────────────────────────────

    def _nested(self, *keys: str, default: Any = None) -> Any:
        val: Any = self._raw
        for k in keys:
            if not isinstance(val, dict):
                return default
            val = val.get(k)
            if val is None:
                return default
        return val

    # ── forgejo ──────────────────────────────────────────────────────

    @property
    def forgejo_url(self) -> str:
        return str(self._nested("forgejo", "url", default="http://localhost:2000"))

    @property
    def forgejo_token(self) -> str | None:
        return self._nested("forgejo", "token")

    # ── platforms ────────────────────────────────────────────────────

    def platform_token(self, name: str) -> str | None:
        return self._nested("platforms", name, "token")

    @property
    def enabled_platforms(self) -> list[str]:
        platforms: dict = self._nested("platforms", default={})
        return [name for name in ("github", "codeberg", "gitlab") if name in platforms]

    # ── import ───────────────────────────────────────────────────────

    @property
    def import_enabled(self) -> bool:
        return bool(self._nested("import", "enabled", default=True))

    @property
    def import_organisations(self) -> list[str]:
        return list(self._nested("import", "organisations", default=[]))

    # ── push mirrors ────────────────────────────────────────────────

    @property
    def push_mirrors_enabled(self) -> bool:
        return bool(self._nested("push_mirrors", "enabled", default=True))

    @property
    def push_mirror_targets(self) -> list[str]:
        return list(self._nested("push_mirrors", "targets", default=[]))

    # ── webhook ──────────────────────────────────────────────────────

    @property
    def webhook_enabled(self) -> bool:
        return bool(self._nested("webhook", "enabled", default=True))

    @property
    def webhook_host(self) -> str:
        return str(self._nested("webhook", "host", default="127.0.0.1"))

    @property
    def webhook_port(self) -> int:
        return int(self._nested("webhook", "port", default=9123))

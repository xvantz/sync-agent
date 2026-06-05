"""Tests for server.py — management HTTP API."""

from __future__ import annotations

import json
from unittest.mock import Mock

from sync_agent.server import SyncAPIHandler


class TestSyncAPIHandler:
    """Test the management API handler directly."""

    def _make_handler(self) -> SyncAPIHandler:
        handler = SyncAPIHandler.__new__(SyncAPIHandler)
        # Mock ForgejoClient properly
        handler.forgejo = Mock()
        handler.forgejo.base_url = "http://localhost:2000"
        handler.forgejo.list_repos = Mock(return_value=[])
        handler.forgejo.list_push_mirrors = Mock(return_value=[])
        handler.platforms = {}
        handler.config = None
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.wfile = Mock()
        return handler

    def test_health_returns_ok(self) -> None:
        handler = self._make_handler()
        handler.path = "/health"
        handler.do_GET()

        handler.send_response.assert_called_once_with(200)
        written = handler.wfile.write.call_args[0][0]
        data = json.loads(written)
        assert data["status"] == "ok"

    def test_not_found_returns_404(self) -> None:
        handler = self._make_handler()
        handler.path = "/nonexistent"
        handler.do_GET()
        handler.send_response.assert_called_once_with(404)

    def test_status_returns_diff(self) -> None:
        handler = self._make_handler()

        from sync_agent.platforms.base import PlatformRepo

        gh = Mock()
        gh.name = "github"
        gh.list_repos = Mock(return_value=[])
        handler.platforms = {"github": gh}
        handler.path = "/status"

        handler.do_GET()

        handler.send_response.assert_called_once_with(200)
        written = handler.wfile.write.call_args[0][0]
        data = json.loads(written)
        assert data["status"] == "ok"
        assert "platform_counts" in data

    def test_status_fails_without_forgejo(self) -> None:
        handler = self._make_handler()
        handler.forgejo = None
        handler.path = "/status"
        handler.do_GET()
        handler.send_response.assert_called_once_with(503)

    def test_sync_returns_result(self) -> None:
        handler = self._make_handler()

        from sync_agent.platforms.base import PlatformRepo

        gh = Mock()
        gh.name = "github"
        gh.list_repos = Mock(return_value=[])
        handler.platforms = {"github": gh}
        handler.path = "/sync"
        handler.do_POST()

        handler.send_response.assert_called_once_with(200)
        written = handler.wfile.write.call_args[0][0]
        data = json.loads(written)
        assert "imported" in data
        assert "push_mirrors_set" in data

    def test_sync_import_only(self) -> None:
        handler = self._make_handler()

        gh = Mock()
        gh.name = "github"
        gh.list_repos = Mock(return_value=[])
        handler.platforms = {"github": gh}
        handler.path = "/sync/import"
        handler.do_POST()

        handler.send_response.assert_called_once_with(200)
        written = handler.wfile.write.call_args[0][0]
        data = json.loads(written)
        assert "imported" in data

"""Tests for webhook.py — auto-create webhook server."""

from __future__ import annotations

import hmac
import io
import json
from unittest.mock import Mock

from sync_agent.forgejo_client import ForgejoClient
from sync_agent.webhook import WebhookHandler


class TestWebhookHandler:
    """Test the webhook HTTP handler logic directly."""

    def _make_handler(
        self,
        forgejo: ForgejoClient | None = None,
        platforms: dict | None = None,
        secret: str = "",
    ) -> WebhookHandler:
        handler = WebhookHandler.__new__(WebhookHandler)
        handler.forgejo = forgejo
        handler.platforms = platforms or {}
        handler.secret = secret
        handler.command = "POST"
        handler.path = "/"
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.wfile = Mock()
        return handler

    def test_repo_created_creates_on_platforms(self) -> None:
        forgejo = Mock(spec=ForgejoClient)
        forgejo.add_push_mirror = Mock()

        gh_provider = Mock()
        gh_provider.create_repo.return_value = Mock()

        handler = self._make_handler(
            forgejo=forgejo,
            platforms={"github": gh_provider},
        )

        event = {
            "action": "created",
            "repository": {
                "name": "new-project",
                "owner": {"login": "xvantz"},
                "description": "A shiny new project",
                "private": True,
            },
        }
        handler._handle_repo_created(event)

        gh_provider.create_repo.assert_called_once_with(
            "new-project", private=True, description="A shiny new project"
        )
        forgejo.add_push_mirror.assert_called_once_with(
            "xvantz", "new-project",
            "git@github.com:xvantz/new-project.git",
        )

    def test_validates_hmac_signature(self) -> None:
        handler = self._make_handler(secret="my-secret")

        body = json.dumps({"action": "created"}).encode()
        expected_sig = "sha256=" + hmac.new(
            b"my-secret", body, "sha256"
        ).hexdigest()

        handler.headers = {
            "X-Forgejo-Signature": expected_sig,
            "Content-Length": str(len(body)),
        }
        handler.rfile = io.BytesIO(body)

        handler.do_POST()

        handler.send_response.assert_called_once_with(200)

    def test_rejects_invalid_signature(self) -> None:
        handler = self._make_handler(secret="my-secret")

        body = json.dumps({"test": "data"}).encode()
        handler.headers = {
            "X-Forgejo-Signature": "sha256:invalid_signature_here",
            "Content-Length": str(len(body)),
        }
        handler.rfile = io.BytesIO(body)

        handler.do_POST()

        handler.send_response.assert_called_once_with(403)

    def test_missing_repo_info_returns_400(self) -> None:
        handler = self._make_handler()
        event = {"action": "created", "repository": {}}
        handler._handle_repo_created(event)
        handler.send_response.assert_called_once_with(400)

    def test_ignores_non_repository_events(self) -> None:
        handler = self._make_handler()

        body = json.dumps({"action": "created"}).encode()
        handler.headers = {
            "X-Forgejo-Event": "ping",
            "Content-Length": str(len(body)),
        }
        handler.rfile = io.BytesIO(body)

        handler.do_POST()

        handler.send_response.assert_called_once_with(200)

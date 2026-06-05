"""Auto-create webhook server — listens for Forgejo repository:created events."""

from __future__ import annotations

import hmac
import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sync_agent.forgejo_client import ForgejoClient
    from sync_agent.platforms.base import PlatformProvider

logger = logging.getLogger(__name__)


class WebhookHandler(BaseHTTPRequestHandler):
    """HTTP handler that processes Forgejo webhook events."""

    # These are set by the factory function
    forgejo: ForgejoClient | None = None
    platforms: dict[str, PlatformProvider] | None = None
    secret: str = ""

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        # Verify signature if secret is set
        if self.secret:
            signature = self.headers.get("X-Forgejo-Signature", "")
            expected = hmac.new(
                self.secret.encode(), body, "sha256"
            ).hexdigest()
            if not hmac.compare_digest(f"sha256={expected}", signature):
                self._respond(403, b'{"error": "invalid signature"}')
                return

        try:
            event = json.loads(body)
        except json.JSONDecodeError:
            self._respond(400, b'{"error": "invalid JSON"}')
            return

        event_type = self.headers.get("X-Forgejo-Event", "")

        if event_type == "repository" and event.get("action") == "created":
            self._handle_repo_created(event)
        else:
            logger.debug("Ignoring event type=%s", event_type)
            self._respond(200, b'{"status": "ignored"}')

    def _handle_repo_created(self, event: dict) -> None:
        """A new repository was created in Forgejo."""
        repo = event.get("repository", {})
        repo_name = repo.get("name", "")
        repo_owner = repo.get("owner", {}).get("login", "")
        description = repo.get("description", "")
        private = repo.get("private", True)

        if not repo_name or not repo_owner:
            self._respond(400, b'{"error": "missing repository info"}')
            return

        logger.info("Auto-creating repo '%s' on cloud platforms...", repo_name)

        errors: list[str] = []
        if self.platforms:
            for platform_name, provider in self.platforms.items():
                try:
                    provider.create_repo(
                        repo_name,
                        private=private,
                        description=description,
                    )
                    logger.info("  ✓ Created on %s", platform_name)

                    # Add push mirror
                    if self.forgejo:
                        remote_url = (
                            f"git@{platform_name}.com:"
                            f"{repo_owner}/{repo_name}.git"
                        )
                        self.forgejo.add_push_mirror(
                            repo_owner, repo_name, remote_url
                        )
                        logger.info(
                            "  ✓ Push mirror set for %s", platform_name
                        )
                except Exception as e:
                    logger.error(
                        "  ✗ Failed on %s: %s", platform_name, e
                    )
                    errors.append(f"{platform_name}: {e}")

        if errors:
            self._respond(
                207,
                json.dumps(
                    {"status": "partial", "errors": errors}
                ).encode(),
            )
        else:
            self._respond(200, b'{"status": "created"}')

    def _respond(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: str) -> None:
        logger.debug(fmt, *args)


def run_webhook(
    forgejo: ForgejoClient,
    platforms: dict[str, PlatformProvider],
    *,
    host: str = "127.0.0.1",
    port: int = 9123,
    secret: str = "",
) -> None:
    """Start the auto-create webhook server (blocking)."""
    # Monkey-patch handler
    WebhookHandler.forgejo = forgejo
    WebhookHandler.platforms = platforms
    WebhookHandler.secret = secret

    server = HTTPServer((host, port), WebhookHandler)
    logger.info(
        "Webhook server listening on http://%s:%d", host, port
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down webhook server")
        server.shutdown()

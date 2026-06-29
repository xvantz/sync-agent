"""HTTP API server — exposes sync status, manual sync trigger, health checks.

Endpoints:
  GET  /health        — health check
  GET  /status        — current sync state (reconciler diff)
  POST /sync          — full sync cycle (run)
  POST /sync/import   — import missing repos
  POST /sync/push     — set up push mirrors
"""

from __future__ import annotations

import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sync_agent.config import Config
    from sync_agent.forgejo_client import ForgejoClient
    from sync_agent.platforms.base import PlatformProvider

logger = logging.getLogger(__name__)


class SyncAPIHandler(BaseHTTPRequestHandler):
    """HTTP handler for the sync management API."""

    forgejo: ForgejoClient | None = None
    platforms: dict[str, PlatformProvider] | None = None
    config: Config | None = None

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"status": "ok", "service": "sync-agent"})
        elif self.path == "/status":
            self._handle_status()
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/sync":
            self._handle_sync(full=True)
        elif self.path == "/sync/import":
            self._handle_sync(full=False, import_only=True)
        elif self.path == "/sync/push":
            self._handle_sync(full=False, push_only=True)
        else:
            self._json(404, {"error": "not found"})

    # ── handlers ─────────────────────────────────────────────────────

    def _handle_status(self) -> None:
        """Run reconciler and return current state."""
        from sync_agent.reconciler import Reconciler

        if not self.forgejo or not self.platforms:
            self._json(503, {"error": "not initialized"})
            return

        try:
            reconciler = Reconciler(self.forgejo, self.platforms)
            diff = reconciler.discover()

            missing = [
                {"platform": p, "name": r.name, "owner": r.owner}
                for p, r in diff.missing_in_forgejo
            ]
            missing_pm = [
                {
                    "repo": r.full_name,
                    "missing_targets": t,
                }
                for r, t in diff.missing_push_mirrors
            ]

            self._json(200, {
                "status": "ok",
                "forgejo_url": self.forgejo.base_url,
                "platform_counts": diff.platform_counts,
                "missing_in_forgejo": {
                    "count": len(missing),
                    "repos": missing[:20],
                },
                "missing_push_mirrors": {
                    "count": len(missing_pm),
                    "repos": missing_pm[:20],
                },
            })
        except Exception as e:
            logger.error("Status failed: %s", e)
            self._json(500, {"error": str(e)})

    def _handle_sync(
        self,
        full: bool = True,
        import_only: bool = False,
        push_only: bool = False,
    ) -> None:
        """Run sync operations."""
        from sync_agent.reconciler import Reconciler

        if not self.forgejo or not self.platforms:
            self._json(503, {"error": "not initialized"})
            return

        try:
            reconciler = Reconciler(self.forgejo, self.platforms)
            diff = reconciler.discover()

            result: dict = {
                "forgejo_url": self.forgejo.base_url,
                "platform_counts": diff.platform_counts,
                "imported": 0,
                "push_mirrors_set": 0,
            }

            # Import
            if full or import_only:
                from sync_agent.importer import Importer

                importer = Importer(self.forgejo, self.platforms)
                imported = importer.run(diff, dry_run=False)
                result["imported"] = imported

            # Push mirrors
            if full or push_only:
                from sync_agent.pusher import Pusher

                pusher = Pusher(self.forgejo, self.platforms)
                setup_count = pusher.run(diff, dry_run=False)
                result["push_mirrors_set"] = setup_count

                # Also sync ALL existing mirrors so code is pushed immediately
                synced = pusher.sync_all_mirrors()
                result["push_mirrors_synced"] = synced

            self._json(200, result)
        except Exception as e:
            logger.error("Sync failed: %s", e)
            self._json(500, {"error": str(e)})

    # ── helpers ──────────────────────────────────────────────────────

    def _json(self, code: int, data: dict) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def log_message(self, fmt: str, *args: str) -> None:
        logger.debug(fmt, *args)


def run_api_server(
    forgejo: ForgejoClient,
    platforms: dict[str, PlatformProvider],
    config: Config,
    *,
    host: str = "127.0.0.1",
    port: int = 9124,
) -> None:
    """Start the management API server (blocking)."""
    SyncAPIHandler.forgejo = forgejo
    SyncAPIHandler.platforms = platforms
    SyncAPIHandler.config = config

    server = HTTPServer((host, port), SyncAPIHandler)
    logger.info(
        "API server listening on http://%s:%d", host, port
    )
    logger.info("  GET  /health        — health check")
    logger.info("  GET  /status        — sync state")
    logger.info("  POST /sync          — full sync")
    logger.info("  POST /sync/import   — import only")
    logger.info("  POST /sync/push     — push mirrors only")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down API server")
        server.shutdown()

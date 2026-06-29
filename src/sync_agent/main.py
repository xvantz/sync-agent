"""CLI entry point for sync-agent."""

from __future__ import annotations

import logging
import sys

import click

from sync_agent.config import Config
from sync_agent.forgejo_client import ForgejoClient
from sync_agent.importer import Importer
from sync_agent.platforms.codeberg import CodebergProvider
from sync_agent.platforms.github import GitHubProvider
from sync_agent.platforms.gitlab import GitLabProvider
from sync_agent.pusher import Pusher
from sync_agent.reconciler import Reconciler
from sync_agent.server import run_api_server
from sync_agent.webhook import run_webhook

logger = logging.getLogger("sync_agent")

# Map platform names to provider classes
_PROVIDERS = {
    "github": GitHubProvider,
    "codeberg": CodebergProvider,
    "gitlab": GitLabProvider,
}


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _init_platforms(
    cfg: Config,
) -> dict[str, GitHubProvider | CodebergProvider | GitLabProvider]:
    """Initialize platform providers from config."""
    platforms: dict[str, GitHubProvider | CodebergProvider | GitLabProvider] = {}
    for name in cfg.enabled_platforms:
        token = cfg.platform_token(name)
        if not token:
            logger.warning("No token for '%s', skipping", name)
            continue
        cls = _PROVIDERS.get(name)
        if cls is None:
            logger.warning("Unknown platform '%s', skipping", name)
            continue
        platforms[name] = cls(token)
    return platforms


@click.group()
@click.option("--config", "-c", default="config.yaml", help="Config file path")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def cli(ctx: click.Context, config: str, verbose: bool) -> None:
    """Sync Agent — synchronise repositories across Git platforms."""
    _setup_logging(verbose)
    try:
        cfg = Config.from_file(config)
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"ERROR: {e}", err=True)
        ctx.exit(1)
    ctx.ensure_object(dict)
    ctx.obj["cfg"] = cfg


@cli.command()
@click.option("--dry-run", "-n", is_flag=True, help="Only show what would be done")
@click.pass_context
def run(ctx: click.Context, dry_run: bool) -> None:
    """Full sync cycle: discover → import → push mirrors."""
    cfg: Config = ctx.obj["cfg"]

    forgejo = ForgejoClient(cfg.forgejo_url, cfg.forgejo_token)
    platforms = _init_platforms(cfg)

    try:
        # 1. Discover & diff
        reconciler = Reconciler(forgejo, platforms)
        logger.info("Discovering repositories on all platforms...")
        diff = reconciler.discover()

        logger.info(
            "Found: Forgejo=%s, %s",
            diff.platform_counts,
            {
                p: c
                for p, c in diff.platform_counts.items()
            },
        )

        # 2. Import missing
        if cfg.import_enabled and diff.missing_in_forgejo:
            logger.info(
                "Repos missing in Forgejo: %d", len(diff.missing_in_forgejo)
            )
            importer = Importer(forgejo, platforms)
            imported = importer.run(diff, dry_run=dry_run)
            if not dry_run:
                logger.info("Imported %d repos", imported)
            else:
                logger.info("Would import %d repos", imported)
        else:
            logger.info("All repos already in Forgejo")

        # 3. Set up push mirrors
        if cfg.push_mirrors_enabled and diff.missing_push_mirrors:
            logger.info(
                "Repos missing push mirrors: %d",
                len(diff.missing_push_mirrors),
            )
            pusher = Pusher(forgejo, platforms)
            setup_count = pusher.run(diff, dry_run=dry_run)
            if not dry_run:
                logger.info("Set up %d push mirrors", setup_count)
                # Sync ALL existing mirrors so code is pushed immediately
                logger.info("Triggering sync on all push mirrors...")
                synced = pusher.sync_all_mirrors()
                if synced:
                    logger.info("Synced %d push mirrors", synced)
            else:
                logger.info("Would set up %d push mirrors", setup_count)
        else:
            logger.info("All push mirrors are in place")

    finally:
        forgejo.close()
        for p in platforms.values():
            p.close()


@cli.command()
@click.option("--dry-run", "-n", is_flag=True)
@click.pass_context
def import_cmd(ctx: click.Context, dry_run: bool) -> None:
    """Import missing repos from cloud platforms into Forgejo."""
    cfg: Config = ctx.obj["cfg"]
    forgejo = ForgejoClient(cfg.forgejo_url, cfg.forgejo_token)
    platforms = _init_platforms(cfg)
    try:
        reconciler = Reconciler(forgejo, platforms)
        diff = reconciler.discover()
        if not diff.missing_in_forgejo:
            logger.info("Nothing to import")
            return
        importer = Importer(forgejo, platforms)
        imported = importer.run(diff, dry_run=dry_run)
        logger.info(
            "%s %d repos",
            "Would import" if dry_run else "Imported",
            imported,
        )
    finally:
        forgejo.close()
        for p in platforms.values():
            p.close()


@cli.command()
@click.option("--dry-run", "-n", is_flag=True)
@click.pass_context
def push_mirrors(ctx: click.Context, dry_run: bool) -> None:
    """Set up push mirrors on all repos."""
    cfg: Config = ctx.obj["cfg"]
    forgejo = ForgejoClient(cfg.forgejo_url, cfg.forgejo_token)
    platforms = _init_platforms(cfg)
    try:
        reconciler = Reconciler(forgejo, platforms)
        diff = reconciler.discover()
        if not diff.missing_push_mirrors:
            logger.info("All push mirrors are set up")
            return
        pusher = Pusher(forgejo, platforms)
        count = pusher.run(diff, dry_run=dry_run)
        logger.info(
            "%s %d push mirrors",
            "Would set up" if dry_run else "Set up",
            count,
        )
    finally:
        forgejo.close()
        for p in platforms.values():
            p.close()


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show current sync state: what's where."""
    cfg: Config = ctx.obj["cfg"]
    forgejo = ForgejoClient(cfg.forgejo_url, cfg.forgejo_token)
    platforms = _init_platforms(cfg)
    try:
        reconciler = Reconciler(forgejo, platforms)
        diff = reconciler.discover()

        click.echo("\n=== Sync Status ===\n")
        click.echo(f"Forgejo: {cfg.forgejo_url}")
        click.echo(
            f"Platforms: {', '.join(diff.platform_counts.keys())}\n"
        )

        for p_name, p_count in diff.platform_counts.items():
            click.echo(f"  {p_name}: {p_count} repos")

        click.echo("")
        if diff.missing_in_forgejo:
            click.echo(
                "🔴 Missing in Forgejo (need import): "
                f"{len(diff.missing_in_forgejo)}"
            )
            for plat, repo in diff.missing_in_forgejo[:10]:
                click.echo(f"   [{plat}] {repo.owner}/{repo.name}")
            if len(diff.missing_in_forgejo) > 10:
                click.echo(
                    f"   ... and {len(diff.missing_in_forgejo) - 10} more"
                )
        else:
            click.echo("🟢 All cloud repos are in Forgejo")

        if diff.missing_push_mirrors:
            click.echo(
                "🟡 Missing push mirrors: "
                f"{len(diff.missing_push_mirrors)} repos"
            )
            for repo, targets in diff.missing_push_mirrors[:10]:
                click.echo(
                    f"   {repo.full_name} → {', '.join(targets)}"
                )
            if len(diff.missing_push_mirrors) > 10:
                click.echo(
                    f"   ... and {len(diff.missing_push_mirrors) - 10} more"
                )
        else:
            click.echo("🟢 All push mirrors are set up")
        click.echo("")
    finally:
        forgejo.close()
        for p in platforms.values():
            p.close()


@cli.command()
@click.option("--port", default=9123, help="Webhook server port")
@click.option("--host", default="127.0.0.1", help="Webhook server host")
@click.pass_context
def webhook(ctx: click.Context, port: int, host: str) -> None:
    """Start the auto-create webhook server."""
    cfg: Config = ctx.obj["cfg"]
    forgejo = ForgejoClient(cfg.forgejo_url, cfg.forgejo_token)
    platforms = _init_platforms(cfg)
    try:
        run_webhook(forgejo, platforms, host=host, port=port)
    finally:
        forgejo.close()
        for p in platforms.values():
            p.close()


@cli.command()
@click.option("--port", default=9124, help="API server port")
@click.option("--host", default="127.0.0.1", help="API server host")
@click.pass_context
def serve(ctx: click.Context, port: int, host: str) -> None:
    """Start the management API server (status, sync trigger)."""
    cfg: Config = ctx.obj["cfg"]
    forgejo = ForgejoClient(cfg.forgejo_url, cfg.forgejo_token)
    platforms = _init_platforms(cfg)
    try:
        run_api_server(forgejo, platforms, cfg, host=host, port=port)
    finally:
        forgejo.close()
        for p in platforms.values():
            p.close()

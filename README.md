# sync-agent 🔄

**Forgejo Sync Agent** — automatic repository synchronization between Forgejo, GitHub, Codeberg, and GitLab.

Forgejo is the single source of truth. Code pushed there is automatically mirrored to all configured platforms — no manual syncing, no drift.

---

## Features

| Feature | Description |
|---------|-------------|
| **Import (Pull Mirror)** | Scans GitHub/Codeberg/GitLab, pulls missing repos into Forgejo as live mirrors |
| **Push Mirror** | Every push to Forgejo is automatically synced to cloud platforms via `sync_on_commit` |
| **Auto-create** | New repo in Forgejo → instantly created on all platforms with push mirror set up |
| **Immediate sync** | `sync-agent run` triggers `sync_all_mirrors` — no waiting for the periodic timer |
| **Repair** | Detects broken push mirrors (target repo missing, `sync_on_commit=False`) and recreates them |
| **Token from file** | Reads tokens from sops-managed env files — works in both systemd services and CLI |
| **Config auto-detect** | Looks for `/etc/sync-agent/config.yaml` first, then `./config.yaml` |
| **NixOS module** | One-liner in `configuration.nix` — timers, webhook, auto-registration included |

---

## Architecture

```
Cloud platforms (GitHub, Codeberg, GitLab)
     │  ▲
     │  │
     ▼  │
  ┌──────┴──────────────────┐
  │      Sync Agent         │
  │                         │
  │  import (Pull) ◄────────│── scans clouds, pulls new repos
  │  push-mirrors   ───────►│── sets up mirrors on clouds
  │  webhook (auto) ◄───────│── listens for repo:created events
  │  serve (API)     ◄──────│── HTTP API for manual control
  └──────┬──────────────────┘
         │
  ┌──────▼──────────────────┐
  │      Forgejo            │  ← single source of truth
  │  localhost:2000         │
  └─────────────────────────┘
         │
         ▼
  sync_on_commit — every push to Forgejo immediately
  triggers the push mirror. No polling, no delays.
```

---

## Quick Start

### NixOS module (recommended)

```nix
{
  imports = [ sync-agent.nixosModules.default ];

  services.forgejo-sync = {
    enable = true;

    forgejo = {
      url = "http://localhost:2000";
      tokenFile = config.sops.secrets.forgejo_admin_env.path;
    };

    platforms.github = {
      enable = true;
      tokenFile = config.sops.secrets.github_admin_env.path;
    };

    import.enable = true;
    pushMirrors.enable = true;
    autoCreate.enable = true;
  };
}
```

Then:

```bash
nix flake update sync-agent
nh os switch

# Check status
sync-agent status

# Full sync cycle
sudo systemctl start sync-agent-run
```

The module sets up:
- `sync-agent-run` — daily full sync (import + push mirrors), also runs 5 min after boot
- `sync-agent-import` — hourly pull from clouds
- `sync-agent-webhook` — persistent webhook server for auto-create
- User webhook registered automatically on first start

### Manual (pip)

```bash
pip install sync-agent

# Create config
cp config.yaml.example config.yaml
# → set tokens (see Configuration section)

# Check state
sync-agent status

# Full sync
sync-agent run
```

---

## CLI Reference

```
Usage: sync-agent [OPTIONS] COMMAND [ARGS]...

Options:
  -c, --config TEXT  Config path (default: auto-detect /etc → ./)
  -v, --verbose      Verbose logging
  --help

Commands:
  run             Full cycle: discover → import → push mirrors + sync all
  status          Show current sync state
  import          Pull missing repos from clouds into Forgejo
  push-mirrors    Set up push mirrors on all repos
  webhook         Start auto-create webhook server
  serve           HTTP API server (status, sync trigger)
  setup-webhook   Register Forgejo webhooks on all repos (--sync-all)
```

### Example usage

```bash
# Check what's missing (dry-run, no changes)
sync-agent run --dry-run

# Full sync cycle
sync-agent run

# One-time import from GitHub
sync-agent import

# Set up push mirrors
sync-agent push-mirrors

# Start webhook server (listens on :9123)
sync-agent webhook

# Start API server (listens on :9124)
sync-agent serve

# Register user webhooks on all existing repos
sync-agent setup-webhook --sync-all
```

---

## HTTP API (serve)

```
GET  /health        → {"status": "ok"}
GET  /status        → full sync state (reconciler diff)
POST /sync          → full sync cycle
POST /sync/import   → import only
POST /sync/push     → push mirrors only (triggers sync_all_mirrors)
```

---

## Configuration

```yaml
forgejo:
  url: "http://localhost:2000"
  # Token — from a file (recommended):
  token_file: "/run/secrets/forgejo_env"
  # Or inline (environment variable, substituted from shell):
  # token: "${FORGEJO_TOKEN}"

platforms:
  github:
    token_file: "/run/secrets/github_admin_env"
    # token: "${GITHUB_TOKEN}"
  codeberg:
    token_file: "/run/secrets/codeberg_token"
  gitlab:
    token_file: "/run/secrets/gitlab_token"

import:
  enabled: true
  # schedule: "hourly"         # systemd OnCalendar format
  # organisations: ["my-org"]  # org repos to pull

push_mirrors:
  enabled: true
  targets: ["github"]          # "github", "codeberg", "gitlab"

webhook:
  enabled: true
  port: 9123
  # host: "127.0.0.1"
```

**Token resolution order:**
1. `token_file` — read `KEY=VALUE` file (sops format), extracts `GITHUB_TOKEN=xxx`
2. `token` — use raw value (supports `${ENV_VAR}` substitution)

---

## How it works

### 1. Discovery & Diff
`reconciler.py` scans Forgejo and all cloud platforms. Computes what's missing where.

### 2. Import (Pull Mirror)
Repos found in the cloud but missing in Forgejo are imported via the Forgejo Migration API as live pull mirrors. Source stays authoritative, Forgejo follows.

### 3. Push Mirror
For every Forgejo repo without a push mirror to a configured target, sync-agent:
1. Creates the repo on the target platform (if it doesn't exist)
2. Adds a push mirror with `sync_on_commit=true`
3. Triggers an immediate sync

**`sync_on_commit`:** Forgejo pushes to the remote on every git push — no polling, no delays.

### 4. Auto-create
A webhook server listens for Forgejo's `repository:created` events (via a user-level system webhook). When a new repo is created in Forgejo, it's automatically:
1. Created on GitHub (and other configured platforms)
2. Fitted with a push mirror

### 5. Broken mirror detection
Push mirrors with `"Repository not found"` errors or `sync_on_commit=False` are detected during discovery and automatically recreated.

---

## Integration with Forgejo

### Required settings

Forgejo's `app.ini` must allow webhooks to localhost:

```ini
[webhook]
ALLOWED_HOST_LIST = 127.0.0.1, localhost
```

In NixOS:

```nix
services.forgejo.settings.webhook = {
  ALLOWED_HOST_LIST = "127.0.0.1, localhost";
};
```

### Token scopes

| Token | Required scopes |
|-------|----------------|
| Forgejo | `write:repository`, `write:user` |
| GitHub | `repo` (full control of private repos) |
| Codeberg | `write:repository` |
| GitLab | `api` |

---

## Project status

- **Phase 1 — Core** ✅ Complete
  - [x] Forgejo API client
  - [x] Platform providers (GitHub, Codeberg, GitLab)
  - [x] Reconciler (discovery + diff)
  - [x] Import (pull mirror)
  - [x] Push mirror setup + sync
  - [x] Broken mirror detection & repair
  - [x] sync_all_mirrors — immediate sync
  - [x] CLI (run, status, import, push-mirrors, webhook, serve)
  - [x] NixOS module with systemd timers
  - [x] 65 tests (unit + integration)
- **Phase 2 — Auto-create webhook** ✅ Complete
  - [x] Webhook server (Python http.server)
  - [x] User webhook auto-registration on module activation
  - [x] Token file support (works in systemd + CLI)
- **Phase 3 — CI/CD** ❌ Not planned
- **Phase 4 — Security** ❌ Not planned

---

## Development

```bash
git clone https://github.com/xvantz/sync-agent
cd sync-agent

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest                          # 65 unit tests
pytest -m integration           # integration tests (needs GitHub token)
pytest --cov=src/sync_agent     # with coverage
```

---

## License

MIT

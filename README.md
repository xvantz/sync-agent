# sync-agent 🔄

**Forgejo Sync Agent** — автоматическая синхронизация репозиториев между Forgejo, GitHub, Codeberg и GitLab.

## Зачем?

Код размазан по облачным платформам. Нет единой точки входа. Если GitHub ляжет — где искать последнюю версию?

**sync-agent решает:**
- **Единый источник истины:** Forgejo — центр. Весь код стекается сюда.
- **Pull Mirror (подсос):** Если репа появилась в облаке, но её нет в Forgejo — sync-agent сам затянет как зеркало.
- **Push Mirror (разнос):** Каждый пуш в Forgejo автоматически улетает на GitHub, Codeberg, GitLab.
- **Auto-create:** Создал репу в Forgejo → она сама появилась на всех платформах.
- **Dry-run:** Любую операцию можно прогнать вхолостую — ничего не сломается.

## Архитектура

```
Облака (GitHub, Codeberg, GitLab)
     │  ▲
     │  │
     ▼  │
  ┌──────┴──────────────┐
  │    Sync Agent       │
  │                     │
  │  import (Pull) ◄────│── сканирует облака, затягивает новое
  │  push-mirrors  ────►│── расставляет зеркала на облака
  │  webhook (auto) ◄───│── слушает создание реп в Forgejo
  │  serve (API)    ◄───│── HTTP API для ручного управления
  └──────┬──────────────┘
         │
  ┌──────▼──────────────┐
  │      Forgejo        │  ← источник истины
  │  localhost:2000     │
  └─────────────────────┘
```

## Быстрый старт

```bash
# Установка
pip install sync-agent

# Или через Nix flake
nix profile install github:xvantz/sync-agent

# Подготовить конфиг
cp config.yaml.example config.yaml
# → вписать токены в config.yaml (или через env vars)

# Посмотреть состояние
sync-agent status -c config.yaml

# Сухой прогон (ничего не меняет)
sync-agent run --dry-run -c config.yaml

# Полный цикл: discover → import → push mirrors
sync-agent run -c config.yaml
```

## CLI

```
Usage: sync-agent [OPTIONS] COMMAND [ARGS]...

Commands:
  run           Полный цикл: discover → import → push mirrors
  status        Показать состояние: что где есть
  import        Импорт из облаков → Forgejo (Pull Mirror)
  push-mirrors  Установка Push Mirror'ов
  webhook       Сервер авто-создания (слушает Forgejo events)
  serve         HTTP API для ручного управления (status, sync trigger)

Options:
  -c, --config TEXT  Путь к конфигу (default: config.yaml)
  -v, --verbose      Подробный вывод
  --help
```

## HTTP API (sync-agent serve)

```
GET  /health        → {"status": "ok"}
GET  /status        → полное состояние синхронизации
POST /sync          → полный цикл синхронизации
POST /sync/import   → только импорт
POST /sync/push     → только push mirror'ы
```

## Конфиг (`config.yaml`)

```yaml
forgejo:
  url: "http://localhost:2000"
  token: "${FORGEJO_TOKEN}"          # подстановка из env

platforms:
  github:
    token: "${GITHUB_TOKEN}"
  codeberg:
    token: "${CODEBERG_TOKEN}"

import:
  enabled: true
  schedule: "hourly"
  organisations: ["my-org"]

push_mirrors:
  enabled: true
  targets: ["github", "codeberg"]

webhook:
  enabled: true
  port: 9123
```

## NixOS Module

```nix
{
  imports = [ sync-agent.nixosModules.default ];

  services.forgejo-sync = {
    enable = true;

    forgejo = {
      url = "http://localhost:2000";
      tokenFile = config.age.secrets.forgejo-token.path;
    };

    platforms.github = {
      enable = true;
      tokenFile = config.age.secrets.github-pat.path;
    };
    platforms.codeberg.enable = true;

    import.enable = true;
    pushMirrors.targets = [ "github" "codeberg" ];
    autoCreate.enable = true;
  };
}
```

## Разработка

```bash
git clone https://github.com/xvantz/sync-agent
cd sync-agent

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Запустить тесты
pytest                           # unit-тесты
pytest -m integration            # интеграционные (нужен GitHub токен)
pytest --cov=src/sync_agent      # с покрытием
```

## Тесты

**68 тестов:**
- 27 unit (config, forgejo client, reconciler, retry, importer, pusher, server, webhook)
- 4 интеграционных (против реального GitHub API)
- retry-логика покрыта полностью (exponential backoff, jitter, retryable/non-retryable errors)

## Лицензия

MIT

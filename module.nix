{ config, lib, pkgs, ... }:

let
  cfg = config.services.forgejo-sync;
  inherit (lib) mkEnableOption mkOption types;
in
{
  options.services.forgejo-sync = {
    enable = mkEnableOption "Forgejo Repository Sync Agent";

    package = mkOption {
      type = types.package;
      default = pkgs.sync-agent;
      description = "The sync-agent package to use.";
    };

    configFile = mkOption {
      type = types.nullOr types.path;
      default = null;
      description = ''
        Path to sync-agent config.yaml. When set, overrides all individual options below.
        The config file supports ${"$"}{ENV_VAR} substitution from environment files.
      '';
    };

    forgejo.url = mkOption {
      type = types.str;
      default = "http://localhost:2000";
      description = "Forgejo instance URL.";
    };

    forgejo.tokenFile = mkOption {
      type = types.nullOr types.path;
      default = null;
      description = "Path to file containing Forgejo API token. Sets FORGEJO_TOKEN env var.";
    };

    platforms = {
      github = {
        enable = mkEnableOption "GitHub sync";
        tokenFile = mkOption {
          type = types.nullOr types.path;
          default = null;
          description = "Path to file containing GitHub PAT. Sets GITHUB_TOKEN env var.";
        };
      };
      codeberg = {
        enable = mkEnableOption "Codeberg sync";
        tokenFile = mkOption {
          type = types.nullOr types.path;
          default = null;
          description = "Path to file containing Codeberg API token. Sets CODEBERG_TOKEN env var.";
        };
      };
      gitlab = {
        enable = mkEnableOption "GitLab sync";
        tokenFile = mkOption {
          type = types.nullOr types.path;
          default = null;
          description = "Path to file containing GitLab PAT. Sets GITLAB_TOKEN env var.";
        };
      };
    };

    import = {
      enable = mkEnableOption "Import (Pull Mirror) sync" // { default = true; };
      schedule = mkOption {
        type = types.str;
        default = "hourly";
        description = "Systemd timer schedule for import.";
      };
      organisations = mkOption {
        type = types.listOf types.str;
        default = [ ];
        description = "Organisations to import repos from.";
      };
    };

    pushMirrors = {
      enable = mkEnableOption "Push Mirror setup" // { default = true; };
      targets = mkOption {
        type = types.listOf (types.enum [ "github" "codeberg" "gitlab" ]);
        default = [ "github" "codeberg" ];
        description = "Target platforms for push mirrors.";
      };
    };

    autoCreate = {
      enable = mkEnableOption "Auto-create webhook server" // { default = true; };
      port = mkOption {
        type = types.port;
        default = 9123;
        description = "Port for the auto-create webhook server.";
      };
      secretFile = mkOption {
        type = types.nullOr types.path;
        default = null;
        description = "Path to file containing webhook secret.";
      };
    };
  };

  config = lib.mkIf cfg.enable (let
    # Collect environment files from tokenFile options
    envFiles = lib.filter (x: x != null) [
      cfg.forgejo.tokenFile
      (if cfg.platforms.github.enable then cfg.platforms.github.tokenFile else null)
      (if cfg.platforms.codeberg.enable then cfg.platforms.codeberg.tokenFile else null)
      (if cfg.platforms.gitlab.enable then cfg.platforms.gitlab.tokenFile else null)
    ];

    # Use manual configFile if set, otherwise use generated one
    effectiveConfig =
      if cfg.configFile != null
      then cfg.configFile
      else "/etc/sync-agent/config.yaml";
  in {
    # Generate config.yaml with env var placeholders — tokens are injected
    # at runtime via systemd EnvironmentFile pointing to sops secrets.
    environment.etc."sync-agent/config.yaml".text =
      let
        dollar = "$";
        platformLine = name: enabled:
          lib.optionalString enabled
            "    ${name}:\n      token: \"${dollar}{${lib.toUpper name}_TOKEN}\"\n";
      in
      ''
        forgejo:
          url: "${cfg.forgejo.url}"
          token: "${dollar}{FORGEJO_TOKEN}"

        platforms:
        ${platformLine "github" cfg.platforms.github.enable}
        ${platformLine "codeberg" cfg.platforms.codeberg.enable}
        ${platformLine "gitlab" cfg.platforms.gitlab.enable}

        import:
          enabled: ${lib.boolToString cfg.import.enable}
          organisations: [${lib.concatStringsSep "," cfg.import.organisations}]

        push_mirrors:
          enabled: ${lib.boolToString cfg.pushMirrors.enable}
          targets: [${lib.concatStringsSep "," cfg.pushMirrors.targets}]

        webhook:
          enabled: ${lib.boolToString cfg.autoCreate.enable}
          port: ${toString cfg.autoCreate.port}
      '';

    # ── Import timer (oneshot) ─────────────────────────────────────
    systemd.services.sync-agent-import = lib.mkIf cfg.import.enable {
      description = "Sync Agent — Import repos from cloud platforms";
      after = [ "network.target" ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        Type = "oneshot";
        DynamicUser = true;
        ExecStart = "${cfg.package}/bin/sync-agent -c ${effectiveConfig} import";
        Restart = "on-failure";
      } // lib.optionalAttrs (envFiles != []) {
        EnvironmentFile = envFiles;
      };
    };

    systemd.timers.sync-agent-import = lib.mkIf cfg.import.enable {
      description = "Sync Agent — Periodic import timer";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = cfg.import.schedule;
        Persistent = true;
      };
    };

    # ── Full sync timer (run + push mirrors) ──────────────────────
    systemd.services.sync-agent-run = lib.mkIf (cfg.import.enable || cfg.pushMirrors.enable) {
      description = "Sync Agent — Full cycle: import + push mirrors";
      after = [ "network.target" ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        Type = "oneshot";
        DynamicUser = true;
        ExecStart = "${cfg.package}/bin/sync-agent -c ${effectiveConfig} run";
        Restart = "on-failure";
      } // lib.optionalAttrs (envFiles != []) {
        EnvironmentFile = envFiles;
      };
    };

    systemd.timers.sync-agent-run = lib.mkIf (cfg.import.enable || cfg.pushMirrors.enable) {
      description = "Sync Agent — Periodic full sync timer";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = "daily";
        Persistent = true;
      };
    };

    # ── Auto-create webhook server (persistent) ───────────────────
    systemd.services.sync-agent-webhook = lib.mkIf cfg.autoCreate.enable {
      description = "Sync Agent — Auto-create webhook server";
      after = [ "network.target" ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        DynamicUser = true;
        ExecStart = "${cfg.package}/bin/sync-agent -c ${effectiveConfig} webhook --port ${toString cfg.autoCreate.port}";
        Restart = "always";
        RestartSec = "5";
      } // lib.optionalAttrs (envFiles != []) {
        EnvironmentFile = envFiles;
      };
    };
  });
}

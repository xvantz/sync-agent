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
      type = types.path;
      description = "Path to sync-agent config.yaml.";
    };

    forgejo.url = mkOption {
      type = types.str;
      default = "http://localhost:2000";
      description = "Forgejo instance URL.";
    };

    forgejo.tokenFile = mkOption {
      type = types.nullOr types.path;
      default = null;
      description = "Path to file containing Forgejo API token.";
    };

    platforms = {
      github = {
        enable = mkEnableOption "GitHub sync";
        tokenFile = mkOption {
          type = types.nullOr types.path;
          default = null;
          description = "Path to file containing GitHub PAT.";
        };
      };

      codeberg = {
        enable = mkEnableOption "Codeberg sync";
        tokenFile = mkOption {
          type = types.nullOr types.path;
          default = null;
          description = "Path to file containing Codeberg API token.";
        };
      };

      gitlab = {
        enable = mkEnableOption "GitLab sync";
        tokenFile = mkOption {
          type = types.nullOr types.path;
          default = null;
          description = "Path to file containing GitLab PAT.";
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

  config = lib.mkIf cfg.enable {
    # Generate config.yaml from module options
    environment.etc."sync-agent/config.yaml".text =
      let
        tokens = ''
              forgejo:
                url: "${cfg.forgejo.url}"
                token: "${builtins.readFile cfg.forgejo.tokenFile}"

              platforms:
            ''
            + lib.optionalString cfg.platforms.github.enable ''
                github:
                  token: "${builtins.readFile cfg.platforms.github.tokenFile}"
            ''
            + lib.optionalString cfg.platforms.codeberg.enable ''
                codeberg:
                  token: "${builtins.readFile cfg.platforms.codeberg.tokenFile}"
            ''
            + lib.optionalString cfg.platforms.gitlab.enable ''
                gitlab:
                  token: "${builtins.readFile cfg.platforms.gitlab.tokenFile}"
            ''
            + ''
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
      in
      tokens;

    # Systemd service for the import timer
    systemd.services.sync-agent-import = lib.mkIf cfg.import.enable {
      description = "Sync Agent — Import repos from cloud platforms";
      after = [ "network.target" "forgejo.service" ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        Type = "oneshot";
        DynamicUser = true;
        ExecStart = "${cfg.package}/bin/sync-agent -c /etc/sync-agent/config.yaml import";
        Restart = "on-failure";
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

    # Systemd service for the auto-create webhook
    systemd.services.sync-agent-webhook = lib.mkIf cfg.autoCreate.enable {
      description = "Sync Agent — Auto-create webhook server";
      after = [ "network.target" "forgejo.service" ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        DynamicUser = true;
        ExecStart = "${cfg.package}/bin/sync-agent -c /etc/sync-agent/config.yaml webhook --port ${toString cfg.autoCreate.port}";
        Restart = "always";
        RestartSec = "5";
      };
    };
  };
}

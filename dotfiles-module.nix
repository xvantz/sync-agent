{ config, lib, pkgs, ... }:
{
  services.forgejo-sync = {
    enable = true;

    # Токены из существующих sops env-файлов (hermes.nix)
    forgejo = {
      url = "http://localhost:2000";
      tokenFile = config.sops.secrets.forgejo_env.path;
    };

    platforms.github = {
      enable = true;
      tokenFile = config.sops.secrets.hermes_env.path;
    };

    import = {
      enable = true;
      schedule = "hourly";
    };

    pushMirrors.enable = false;
    autoCreate.enable = false;
  };
}

{
  description = "sync-agent: Forgejo Repository Sync Ecosystem";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      ...
    }:
    flake-utils.lib.eachDefaultSystem (system: {
      packages.default =
        let
          pkgs = import nixpkgs { inherit system; };
          python = pkgs.python3;
        in
        python.pkgs.buildPythonPackage rec {
          pname = "sync-agent";
          version = "0.1.0";
          pyproject = true;
          src = ./.;

          nativeBuildInputs = with pkgs; [
            python.pkgs.setuptools
          ];

          propagatedBuildInputs = with python.pkgs; [
            click
            pyyaml
            httpx
            pydantic
          ];

          meta = {
            description = "Forgejo sync agent — synchronise repos across GitHub, Codeberg, GitLab";
            homepage = "https://github.com/xvantz/sync-agent";
            license = pkgs.lib.licenses.mit;
          };
        };
    })
    // {
      nixosModules.default = import ./module.nix;
    };
}

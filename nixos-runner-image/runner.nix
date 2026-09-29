{ lib, pkgs, ... }:

let
  githubRunner = pkgs.github-runner.override { nodeRuntimes = [ "node24" ]; };
  githubRunnerLauncher = pkgs.writeShellScript "github-runner-jit" ''
    set -euo pipefail
    export HOME=/home/runner
    export RUNNER_ROOT=/var/lib/github-runner
    cd /var/lib/github-runner
    exec ${githubRunner}/bin/run.sh "$@"
  '';
in
{
  boot.kernel.sysctl."vm.overcommit_memory" = 1;

  nix.settings = {
    experimental-features = [ "nix-command" "flakes" "auto-allocate-uids" "cgroups" ];
    auto-allocate-uids = true;
    allow-new-privileges = true;
    extra-system-features = [ "uid-range" ];
  };

  virtualisation.docker = {
    enable = true;
    daemon.settings = {
      log-driver = "local";
      log-opts = {
        max-size = "10m";
        max-file = "3";
      };
    };
  };

  services.qemuGuest.enable = true;
  services.openssh.enable = lib.mkForce false;

  users.groups.runner.gid = 1001;
  users.users.runner = {
    isNormalUser = true;
    uid = 1001;
    group = "runner";
    extraGroups = [ "docker" ];
    home = "/home/runner";
    shell = pkgs.bashInteractive;
  };
  users.users.root.initialHashedPassword = lib.mkForce "!";

  security.sudo.extraRules = [
    {
      users = [ "runner" ];
      commands = [
        {
          command = "ALL";
          options = [ "NOPASSWD" ];
        }
      ];
    }
  ];

  environment.systemPackages = with pkgs; [
    bash
    coreutils
    curl
    diffutils
    docker
    docker-compose
    findutils
    gawk
    gitea-actions-runner
    git
    githubRunner
    gnugrep
    gnused
    jq
    openssh
    perl
    procps
    sudo
    gnutar
    unzip
    which
  ];

  systemd.tmpfiles.rules = [
    "d /var/lib/github-runner 0750 runner runner -"
    "d /opt/runner 0755 root root -"
    "L+ /opt/runner/run.sh - - - - ${githubRunnerLauncher}"
    "L+ /opt/runner/act_runner - - - - ${pkgs.gitea-actions-runner}/bin/gitea-runner"
  ];
}

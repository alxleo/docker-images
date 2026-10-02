{ lib, pkgs, ... }:

let
  githubRunner = pkgs.github-runner.override { nodeRuntimes = [ "node24" ]; };
  runnerTools = with pkgs; [
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
  githubRunnerLauncher = pkgs.writeShellScript "github-runner-jit" ''
    set -euo pipefail
    export HOME=/home/runner
    export RUNNER_ROOT=/var/lib/github-runner
    cd /var/lib/github-runner
    exec ${githubRunner}/bin/run.sh "$@"
  '';
  controllerCaBundle = pkgs.writeShellScript "garm-controller-ca" ''
    set -euo pipefail
    seed=/var/lib/cloud/seed/nocloud-net/user-data
    output=/run/garm/controller-ca.pem
    tmp=$(${pkgs.coreutils}/bin/mktemp)
    trap '${pkgs.coreutils}/bin/rm -f "$tmp"' EXIT
    ${pkgs.coreutils}/bin/mkdir -p /run/garm
    ${pkgs.gawk}/bin/awk '
      {
        line = $0
        sub(/^[[:space:]]*/, "", line)
      }
      line == "-----BEGIN CERTIFICATE-----" { in_cert = 1 }
      in_cert { print line }
      line == "-----END CERTIFICATE-----" { in_cert = 0 }
    ' "$seed" > "$tmp"
    ${pkgs.coreutils}/bin/cat ${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt "$tmp" > "$output"
    ${pkgs.coreutils}/bin/chmod 0644 "$output"
  '';
  runnerProxyEnvironment = pkgs.writeShellScript "garm-runner-proxy-environment" ''
    set -euo pipefail
    seed=/var/lib/cloud/seed/nocloud-net/user-data
    output=/run/garm/proxy.env
    tmp=$(${pkgs.coreutils}/bin/mktemp)
    trap '${pkgs.coreutils}/bin/rm -f "$tmp"' EXIT
    encoded_script=$(${pkgs.gawk}/bin/awk '
      /^write_files:/ { in_write_files = 1; next }
      in_write_files && /^[^[:space:]]/ { in_write_files = 0 }
      in_write_files && /^[[:space:]]*-[[:space:]]+encoding:/ { content = "" }
      in_write_files && /^[[:space:]]+content:/ {
        line = $0
        sub(/^[[:space:]]+content:[[:space:]]*/, "", line)
        content = line
      }
      in_write_files && /^[[:space:]]+path:[[:space:]]*\/install_runner[.]sh[[:space:]]*$/ {
        print content
        exit
      }
    ' "$seed")
    ${pkgs.coreutils}/bin/printf '%s' "$encoded_script" \
      | ${pkgs.coreutils}/bin/base64 --decode > "$tmp"
    controller_url=$(${pkgs.gnused}/bin/sed -n \
      's/^[[:space:]]*METADATA_URL="\([^"]*\)".*/\1/p' "$tmp" \
      | ${pkgs.coreutils}/bin/head -n 1)
    controller_host=$(${pkgs.coreutils}/bin/printf '%s\n' "$controller_url" \
      | ${pkgs.gnused}/bin/sed -E 's#^https://(\[[^]]+\]|[^:/]+)(:[0-9]+)?(/.*)?$#\1#')
    proxy_url="http://$controller_host:3128"
    no_proxy="127.0.0.1,localhost,::1,$controller_host"
    ${pkgs.coreutils}/bin/mkdir -p /run/garm
    ${pkgs.coreutils}/bin/cat > "$output" <<EOF
    HTTP_PROXY=$proxy_url
    HTTPS_PROXY=$proxy_url
    NO_PROXY=$no_proxy
    http_proxy=$proxy_url
    https_proxy=$proxy_url
    no_proxy=$no_proxy
    EOF
    ${pkgs.coreutils}/bin/chmod 0644 "$output"
  '';
in
{
  boot.kernel.sysctl."vm.overcommit_memory" = 1;

  nix.settings = {
    experimental-features = [ "nix-command" "flakes" "auto-allocate-uids" "cgroups" ];
    auto-allocate-uids = true;
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
  virtualisation.incus.agent.enable = true;
  services.openssh.enable = lib.mkForce false;

  environment.sessionVariables.CURL_CA_BUNDLE = "/run/garm/controller-ca.pem";

  services.cloud-init = {
    enable = true;
    network.enable = false;
    extraPackages = runnerTools;
    settings.datasource_list = [ "NoCloud" ];
    settings.cloud_init_modules = lib.mkForce [
      "migrator"
      "seed_random"
      "bootcmd"
      "write-files"
      "growpart"
      "resizefs"
      "update_hostname"
      "resolv_conf"
      "rsyslog"
    ];
  };

  systemd.services.garm-controller-ca = {
    description = "Prepare the GARM controller CA bundle";
    after = [ "cloud-init-local.service" "incus-agent.service" ];
    before = [ "cloud-final.service" ];
    unitConfig.ConditionPathExists = "/var/lib/cloud/seed/nocloud-net/user-data";
    serviceConfig = {
      Type = "oneshot";
      ExecStart = controllerCaBundle;
      RemainAfterExit = true;
    };
  };
  systemd.services.garm-runner-proxy-environment = {
    description = "Prepare the GARM runner proxy environment";
    after = [ "cloud-init-local.service" "incus-agent.service" ];
    before = [ "docker.service" "cloud-final.service" ];
    unitConfig.ConditionPathExists = "/var/lib/cloud/seed/nocloud-net/user-data";
    serviceConfig = {
      Type = "oneshot";
      ExecStart = runnerProxyEnvironment;
      RemainAfterExit = true;
    };
  };
  systemd.services.docker = {
    requires = lib.mkAfter [ "garm-runner-proxy-environment.service" ];
    after = lib.mkAfter [ "garm-runner-proxy-environment.service" ];
    serviceConfig.EnvironmentFile = "-/run/garm/proxy.env";
  };
  systemd.services.cloud-init-local.after = lib.mkAfter [ "incus-agent.service" ];
  systemd.services.cloud-final = {
    requires = lib.mkAfter [
      "docker.service"
      "garm-controller-ca.service"
      "garm-runner-proxy-environment.service"
    ];
    after = lib.mkAfter [
      "docker.service"
      "garm-controller-ca.service"
      "garm-runner-proxy-environment.service"
    ];
    environment.CURL_CA_BUNDLE = "/run/garm/controller-ca.pem";
    serviceConfig.EnvironmentFile = "-/run/garm/proxy.env";
  };

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

  environment.systemPackages = runnerTools;

  systemd.tmpfiles.rules = [
    "d /var/lib/github-runner 0750 runner runner -"
    "d /opt/runner 0755 root root -"
    "d /opt/garm 0755 root root -"
    "L+ /bin/bash - - - - ${pkgs.bash}/bin/bash"
    "L+ /opt/runner/run.sh - - - - ${githubRunnerLauncher}"
    "L+ /opt/runner/act_runner - - - - ${pkgs.gitea-actions-runner}/bin/gitea-runner"
    "L+ /opt/garm/github-runner - - - - ${githubRunner}"
  ];
}

{ config, lib, pkgs, ... }:

let
  proxyUrl = "http://10.203.187.1:3128";
  noProxy = "127.0.0.1,localhost,::1,10.203.187.1";
  proxyEnvironment = {
    HTTP_PROXY = proxyUrl;
    HTTPS_PROXY = proxyUrl;
    NO_PROXY = noProxy;
    http_proxy = proxyUrl;
    https_proxy = proxyUrl;
    no_proxy = noProxy;
  };

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
    github-runner
    gnugrep
    gnused
    jq
    openssh
    perl
    procps
    sudo
    systemd
    gnutar
    unzip
    which
  ];

  controllerCaBundle = pkgs.writeShellScriptBin "garm-controller-ca" ''
    set -euo pipefail

    seed=/var/lib/cloud/seed/nocloud-net/user-data
    output=/run/garm/controller-ca.pem
    tmp=$(${pkgs.coreutils}/bin/mktemp)
    trap '${pkgs.coreutils}/bin/rm -f "$tmp"' EXIT

    ${pkgs.coreutils}/bin/mkdir -p /run/garm
    if [ -r "$seed" ]; then
      ${pkgs.gawk}/bin/awk '
        {
          line = $0
          sub(/^[[:space:]]*/, "", line)
        }
        line == "-----BEGIN CERTIFICATE-----" { in_cert = 1 }
        in_cert { print line }
        line == "-----END CERTIFICATE-----" { in_cert = 0 }
      ' "$seed" > "$tmp"
    fi

    ${pkgs.coreutils}/bin/cat ${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt "$tmp" > "$output"
    ${pkgs.coreutils}/bin/chmod 0644 "$output"
  '';

  metadata = pkgs.runCommand "garm-runner-x86_64-metadata.tar.xz" {
    nativeBuildInputs = [ pkgs.gnutar pkgs.xz ];
  } ''
    image=$TMPDIR/image
    mkdir -p "$image/templates"
    cp ${./metadata.yaml} "$image/metadata.yaml"
    cp ${./templates/meta-data.tpl} "$image/templates/meta-data.tpl"
    cp ${./templates/network-config.tpl} "$image/templates/network-config.tpl"
    cp ${./templates/user-data.tpl} "$image/templates/user-data.tpl"
    cp ${./templates/vendor-data.tpl} "$image/templates/vendor-data.tpl"
    tar --create --file=- \
      --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
      --directory="$image" metadata.yaml templates \
      | xz --compress --check=crc32 > "$out"
  '';
in
{
  system.stateVersion = "26.05";

  networking.hostName = "garm-runner";
  networking.useDHCP = lib.mkDefault true;
  networking.proxy = {
    default = proxyUrl;
    noProxy = noProxy;
  };

  boot.kernel.sysctl."vm.overcommit_memory" = 1;

  virtualisation.incus.agent.enable = true;
  virtualisation.docker.enable = true;

  # Docker pulls need the same egress path as the bootstrap script. The CLI
  # configuration also injects the proxy into containers created by jobs.
  systemd.services.docker.environment = proxyEnvironment;
  environment.etc."docker/cli/config.json".text = builtins.toJSON {
    proxies.default = {
      httpProxy = proxyUrl;
      httpsProxy = proxyUrl;
      inherit noProxy;
    };
  };

  services.cloud-init = {
    enable = true;
    network.enable = true;
    extraPackages = runnerTools ++ [ controllerCaBundle ];
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
      "users-groups"
    ];
  };

  # NixOS has no distro update-ca-certificates command and cloud-init's
  # NixOS distro path does not support cc_ca_certs. Extract the controller
  # certificate before cloud-final and give its children the combined bundle.
  systemd.services.garm-controller-ca = {
    description = "Prepare the GARM controller CA bundle";
    after = [ "cloud-init-local.service" "incus-agent.service" ];
    before = [ "cloud-final.service" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${controllerCaBundle}/bin/garm-controller-ca";
      RemainAfterExit = true;
    };
  };

  systemd.services.cloud-init-local.after = lib.mkAfter [ "incus-agent.service" ];
  systemd.services.cloud-init-local.environment = proxyEnvironment;
  systemd.services.cloud-init.environment = proxyEnvironment;
  systemd.services.cloud-config.environment = proxyEnvironment;
  systemd.services.cloud-final = {
    wants = lib.mkAfter [ "garm-controller-ca.service" ];
    after = lib.mkAfter [ "garm-controller-ca.service" ];
    environment = proxyEnvironment // {
      CURL_CA_BUNDLE = "/run/garm/controller-ca.pem";
    };
  };

  users.groups.runner = { };
  users.users.runner = {
    description = "GARM runner";
    extraGroups = [ "docker" ];
    group = "runner";
    home = "/home/runner";
    isNormalUser = true;
    shell = pkgs.bashInteractive;
  };

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

  environment.systemPackages = runnerTools ++ [ controllerCaBundle ];
  environment.sessionVariables = proxyEnvironment // {
    CURL_CA_BUNDLE = "/run/garm/controller-ca.pem";
    DOCKER_CONFIG = "/etc/docker/cli";
  };

  systemd.tmpfiles.rules = [
    "d /opt/garm 0755 runner runner -"
    "L+ /opt/garm/github-runner - - - - ${pkgs.github-runner}"
    "L+ /opt/garm/gitea-runner - - - - ${pkgs.gitea-actions-runner}/bin/act_runner"
  ];

  system.build.metadata = metadata;
}

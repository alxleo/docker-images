{ config, lib, pkgs, ... }:

let
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

  runnerProxyEnvironment = pkgs.writeShellScriptBin "garm-runner-proxy-environment" ''
    set -euo pipefail

    seed=/var/lib/cloud/seed/nocloud-net/user-data
    output=/run/garm/proxy.env
    docker_config=/etc/docker/cli/config.json
    tmp=$(${pkgs.coreutils}/bin/mktemp)
    trap '${pkgs.coreutils}/bin/rm -f "$tmp"' EXIT

    controller_url=$(${pkgs.gnused}/bin/sed -n \
      's/^[[:space:]]*METADATA_URL="\([^"]*\)".*/\1/p' "$seed" \
      | ${pkgs.coreutils}/bin/head -n 1)
    controller_host=$(${pkgs.coreutils}/bin/printf '%s\n' "$controller_url" \
      | ${pkgs.gnused}/bin/sed -E 's#^https://(\[[^]]+\]|[^:/]+)(:[0-9]+)?(/.*)?$#\1#')

    if [ -z "$controller_host" ] || [ "$controller_host" = "$controller_url" ]; then
      echo "could not derive the GARM controller host from NoCloud user-data" >&2
      exit 1
    fi

    proxy_url="http://$controller_host:3128"
    no_proxy="127.0.0.1,localhost,::1,$controller_host"

    ${pkgs.coreutils}/bin/mkdir -p /run/garm /etc/docker/cli
    ${pkgs.coreutils}/bin/cat >"$tmp" <<EOF
    HTTP_PROXY=$proxy_url
    HTTPS_PROXY=$proxy_url
    NO_PROXY=$no_proxy
    http_proxy=$proxy_url
    https_proxy=$proxy_url
    no_proxy=$no_proxy
    DOCKER_CONFIG=/etc/docker/cli
    EOF
    ${pkgs.coreutils}/bin/install -m 0644 "$tmp" "$output"

    ${pkgs.coreutils}/bin/cat >"$tmp" <<EOF
    {"proxies":{"default":{"httpProxy":"$proxy_url","httpsProxy":"$proxy_url","noProxy":"$no_proxy"}}}
    EOF
    ${pkgs.coreutils}/bin/install -m 0644 "$tmp" "$docker_config"
  '';

  metadataDefinition = pkgs.writeText "metadata.yaml" (builtins.toJSON {
    architecture = "x86_64";
    creation_date = 1;
    properties = {
      description = "NixOS x86_64 GARM runner VM";
      os = "NixOS";
      release = "26.05";
    };
    templates = {
      "/var/lib/cloud/seed/nocloud-net/meta-data" = {
        when = [ "create" "copy" ];
        template = "meta-data.tpl";
      };
      "/var/lib/cloud/seed/nocloud-net/network-config" = {
        when = [ "create" "copy" ];
        template = "network-config.tpl";
      };
      "/var/lib/cloud/seed/nocloud-net/user-data" = {
        when = [ "create" "copy" ];
        template = "user-data.tpl";
      };
      "/var/lib/cloud/seed/nocloud-net/vendor-data" = {
        when = [ "create" "copy" ];
        template = "vendor-data.tpl";
      };
    };
  });

  metadata = pkgs.runCommand "garm-runner-x86_64-metadata.tar.xz" {
    nativeBuildInputs = [ pkgs.gnutar pkgs.xz ];
  } ''
    image=$TMPDIR/image
    mkdir -p "$image/templates"
    cp ${metadataDefinition} "$image/metadata.yaml"
    cp ${./templates/meta-data.tpl} "$image/templates/meta-data.tpl"
    cp ${./templates/network-config.tpl} "$image/templates/network-config.tpl"
    cp ${./templates/user-data.tpl} "$image/templates/user-data.tpl"
    cp ${./templates/vendor-data.tpl} "$image/templates/vendor-data.tpl"
    tar --create --file=- \
      --sort=name --mtime=@1 --owner=0 --group=0 --numeric-owner \
      --directory="$image" metadata.yaml templates \
      | xz --compress --check=crc32 > "$out"
  '';

in
{
  system.stateVersion = "26.05";

  networking.hostName = "garm-runner";
  networking.useDHCP = lib.mkDefault true;

  boot.kernel.sysctl."vm.overcommit_memory" = 1;

  virtualisation.incus.agent.enable = true;
  virtualisation.docker.enable = true;

  # Derive the local controller and proxy address from GARM's per-instance
  # cloud-init data. This keeps the public image free of private topology.
  systemd.services.garm-runner-proxy-environment = {
    description = "Prepare the GARM runner proxy environment";
    after = [ "cloud-init-local.service" "incus-agent.service" ];
    before = [ "docker.service" "cloud-final.service" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${runnerProxyEnvironment}/bin/garm-runner-proxy-environment";
      RemainAfterExit = true;
    };
  };
  systemd.services.docker = {
    requires = lib.mkAfter [ "garm-runner-proxy-environment.service" ];
    after = lib.mkAfter [ "garm-runner-proxy-environment.service" ];
    serviceConfig.EnvironmentFile = "/run/garm/proxy.env";
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
    environment = {
      CURL_CA_BUNDLE = "/run/garm/controller-ca.pem";
    };
    serviceConfig.EnvironmentFile = "/run/garm/proxy.env";
  };

  users.groups.runner = { };
  users.users.root.initialHashedPassword = lib.mkForce "!";
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

  services.openssh.enable = lib.mkForce false;

  environment.systemPackages = runnerTools ++ [ controllerCaBundle runnerProxyEnvironment ];
  environment.sessionVariables = {
    CURL_CA_BUNDLE = "/run/garm/controller-ca.pem";
  };

  systemd.tmpfiles.rules = [
    "d /opt/garm 0755 runner runner -"
    "L+ /opt/garm/github-runner - - - - ${pkgs.github-runner}"
    "L+ /opt/garm/gitea-runner - - - - ${pkgs.gitea-actions-runner}/bin/act_runner"
  ];

  system.build.garmMetadata = metadata;
}

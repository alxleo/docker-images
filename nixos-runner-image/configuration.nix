{ config, lib, modulesPath, pkgs, ... }:

let
  metadataDefinition = pkgs.writeText "metadata.yaml" (builtins.toJSON {
    architecture = "x86_64";
    creation_date = 1;
    properties = {
      description = "NixOS x86_64 CI runner VM";
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
in

{
  imports = [
    "${modulesPath}/virtualisation/kubevirt.nix"
    ./runner.nix
  ];

  system.stateVersion = "26.05";

  boot.loader.grub.enable = lib.mkForce false;
  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = false;

  fileSystems."/boot" = {
    device = "/dev/disk/by-label/ESP";
    fsType = "vfat";
  };

  image.baseName = "nixos-runner";
  system.build.kubevirtImage = lib.mkForce (import "${modulesPath}/../lib/make-disk-image.nix" {
    inherit lib config pkgs;
    inherit (config.image) baseName;
    format = "qcow2";
    diskSize = 16384;
    partitionTableType = "efi";
  });

  networking.hostName = "nixos-runner";
  networking.useDHCP = lib.mkDefault true;

  system.build.garmMetadata = pkgs.runCommand "nixos-runner-metadata.tar.xz" {
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
}

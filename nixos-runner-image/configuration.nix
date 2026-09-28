{ config, lib, modulesPath, pkgs, ... }:

{
  imports = [
    "${modulesPath}/virtualisation/kubevirt.nix"
    ./runner.nix
  ];

  system.stateVersion = "26.05";

  image.baseName = "nixos-runner";
  system.build.kubevirtImage = lib.mkForce (import "${modulesPath}/../lib/make-disk-image.nix" {
    inherit lib config pkgs;
    inherit (config.image) baseName;
    format = "qcow2";
    diskSize = 32768;
  });

  networking.hostName = "nixos-runner";
  networking.useDHCP = lib.mkDefault true;
}

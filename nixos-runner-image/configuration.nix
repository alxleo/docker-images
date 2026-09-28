{ lib, modulesPath, ... }:

{
  imports = [
    "${modulesPath}/virtualisation/kubevirt.nix"
    ./runner.nix
  ];

  system.stateVersion = "26.05";

  image.baseName = "nixos-runner";
  virtualisation.diskSize = 32768;

  networking.hostName = "nixos-runner";
  networking.useDHCP = lib.mkDefault true;
}

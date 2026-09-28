{
  description = "Pinned NixOS Incus VM image for GARM runners";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/6aefcda9401be8acc2b74244fb3b37520ea1f0a8";

  outputs = { nixpkgs, ... }:
    let
      system = "x86_64-linux";
      configuration = nixpkgs.lib.nixosSystem {
        inherit system;
        modules = [
          "${nixpkgs}/nixos/modules/virtualisation/incus-virtual-machine.nix"
          ./configuration.nix
        ];
      };
    in
    {
      nixosConfigurations.garm-runner = configuration;

      packages.${system} = {
        garm-runner-qcow2 = configuration.config.system.build.qemuImage;
        garm-runner-metadata = configuration.config.system.build.garmMetadata;
      };

      checks.${system}.garm-runner = configuration.config.system.build.toplevel;
    };
}

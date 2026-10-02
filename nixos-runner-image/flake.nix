{
  description = "NixOS CI runner container disk";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/6aefcda9401be8acc2b74244fb3b37520ea1f0a8";

  outputs = { nixpkgs, ... }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      configuration = nixpkgs.lib.nixosSystem {
        inherit system;
        modules = [ ./configuration.nix ];
      };
    in
    {
      nixosModules.default = import ./runner.nix;
      nixosConfigurations.nixos-runner = configuration;
      packages.${system} = {
        nixos-runner-qcow2 = configuration.config.system.build.image;
        garm-metadata = configuration.config.system.build.garmMetadata;
      };
      checks.${system} = {
        nixos-runner = configuration.config.system.build.toplevel;
        runner-capabilities = pkgs.testers.runNixOSTest {
          name = "nixos-runner-capabilities";
          nodes.machine = { ... }: {
            imports = [ ./runner.nix ];
            system.stateVersion = "26.05";
            virtualisation.memorySize = 2048;
          };
          testScript = ''
            machine.start()
            machine.wait_for_unit("network-online.target")
            machine.succeed("ip -o link show up | grep -v ' lo '")
            machine.wait_for_unit("docker.service")
            machine.succeed("docker info")
            machine.succeed("docker compose version")
            machine.succeed("Runner.Listener --version")
            machine.succeed("/opt/runner/act_runner --version")
            machine.succeed("test -x /opt/runner/run.sh")
            machine.succeed("sudo -u runner timeout 10 /opt/runner/run.sh --help")
          '';
        };
      };
    };
}

#!/usr/bin/env python3
"""Validate and render the repository-owned ToolHive MCP fleet."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FLEET = ROOT / "mcp-fleet.json"
SHARED_IMAGES = ROOT / "mcp-images.json"
SOURCE_TYPES = {"npx", "uvx", "oci", "remote"}
STATES = {"ready", "legacy-wrapper"}
NAME_PATTERN = re.compile(r"^mcp-[a-z0-9-]+$")
ENV_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
VERSION_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]+)*(?:[-+][0-9A-Za-z.-]+)?$")


class FleetError(ValueError):
    """A fleet declaration is invalid or cannot be executed safely."""


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise FleetError(f"{path}: {exc}") from exc


def load_fleet(path: Path) -> dict[str, Any]:
    fleet = load_json(path)
    if not isinstance(fleet, dict):
        raise FleetError(f"{path}: root must be an object")
    return fleet


def expected_shared_source(entry: dict[str, Any]) -> tuple[str, str] | None:
    build_args = dict(
        line.split("=", 1)
        for line in entry.get("build_args", "").splitlines()
        if "=" in line
    )
    if entry["dockerfile"] == "Dockerfile.npm":
        package_spec = build_args.get("MCP_PACKAGE", "")
        package, separator, version = package_spec.rpartition("@")
        if not separator or not package or not version:
            raise FleetError(f"{entry['name']}: cannot parse MCP_PACKAGE={package_spec!r}")
        return package, version
    if entry["name"] == "mcp-arxiv":
        return "arxiv-mcp-server", build_args["ARXIV_MCP_VERSION"]
    return None


def validate_fleet(fleet: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if fleet.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    version = fleet.get("toolhive_version")
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        errors.append("toolhive_version must be an exact version")
    mcpjam_version = fleet.get("mcpjam_version")
    if not isinstance(mcpjam_version, str) or not VERSION_PATTERN.fullmatch(mcpjam_version):
        errors.append("mcpjam_version must be an exact version")
    if fleet.get("secrets_provider") != "environment":
        errors.append("secrets_provider must be environment")
    if not isinstance(fleet.get("group"), str) or not fleet["group"]:
        errors.append("group must be a non-empty string")
    defaults = fleet.get("defaults")
    if not isinstance(defaults, dict):
        errors.append("defaults must be an object")
        defaults = {}
    if defaults.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        errors.append("the default host must be loopback")
    if defaults.get("proxy_mode") != "streamable-http":
        errors.append("the default proxy_mode must be streamable-http")
    if not isinstance(defaults.get("isolate_network"), bool):
        errors.append("the default isolate_network must be boolean")

    runtimes = fleet.get("runtimes")
    if not isinstance(runtimes, dict):
        errors.append("runtimes must be an object")
        runtimes = {}
    if runtimes.get("npx") != "node:26-alpine":
        errors.append("npx runtime must be node:26-alpine (ToolHive's npx template requires apk)")
    if runtimes.get("uvx") != "python:3.14-slim":
        errors.append("uvx runtime must be python:3.14-slim")

    servers = fleet.get("servers")
    if not isinstance(servers, list) or not servers:
        return errors + ["servers must be a non-empty array"]

    shared_entries = {entry["name"]: entry for entry in load_json(SHARED_IMAGES)}
    expected_names = set(shared_entries) | {"mcp-reddit", "mcp-substack"}
    actual_names: list[str] = []
    ports: list[int] = []
    target_ports: list[int] = []

    for index, server in enumerate(servers):
        where = f"servers[{index}]"
        if not isinstance(server, dict):
            errors.append(f"{where} must be an object")
            continue
        name = server.get("name")
        if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
            errors.append(f"{where}.name must match {NAME_PATTERN.pattern}")
            continue
        where = name
        actual_names.append(name)

        port = server.get("port")
        if not isinstance(port, int) or not 1024 <= port <= 65535:
            errors.append(f"{where}: port must be an integer from 1024 to 65535")
        else:
            ports.append(port)

        state = server.get("state")
        if state not in STATES:
            errors.append(f"{where}: state must be one of {sorted(STATES)}")
        if state == "legacy-wrapper" and not server.get("remove_when"):
            errors.append(f"{where}: legacy-wrapper requires remove_when")
        if state == "ready" and server.get("remove_when"):
            errors.append(f"{where}: ready workloads cannot declare remove_when")

        source = server.get("source")
        if not isinstance(source, dict) or source.get("type") not in SOURCE_TYPES:
            errors.append(f"{where}: source.type must be one of {sorted(SOURCE_TYPES)}")
            continue
        source_type = source["type"]
        if source_type in {"npx", "uvx"}:
            package = source.get("package")
            source_version = source.get("version")
            if not isinstance(package, str) or not package:
                errors.append(f"{where}: {source_type} source requires package")
            if not isinstance(source_version, str) or not VERSION_PATTERN.fullmatch(source_version):
                errors.append(f"{where}: {source_type} source requires an exact version")
        elif source_type == "oci":
            image = source.get("image")
            if not isinstance(image, str) or ":" not in image or image.endswith(":latest"):
                errors.append(f"{where}: OCI source must use a non-latest tag")
            target_port = source.get("target_port")
            if not isinstance(target_port, int) or not 1 <= target_port <= 65535:
                errors.append(f"{where}: OCI source requires target_port")
            else:
                target_ports.append(target_port)
        elif source_type == "remote":
            url = source.get("url")
            if not isinstance(url, str) or not url.startswith("https://"):
                errors.append(f"{where}: remote source requires an HTTPS URL")

        if server.get("network") and server.get(
            "isolate_network", defaults.get("isolate_network", True)
        ):
            errors.append(
                f"{where}: ToolHive network isolation is not enforceable with a custom Docker network"
            )

        for secret in server.get("secrets", []):
            if not isinstance(secret, dict):
                errors.append(f"{where}: every secret must be an object")
                continue
            if not ENV_PATTERN.fullmatch(secret.get("name", "")):
                errors.append(f"{where}: invalid secret name {secret.get('name')!r}")
            if not ENV_PATTERN.fullmatch(secret.get("target", "")):
                errors.append(f"{where}: invalid secret target {secret.get('target')!r}")

        header_secrets = server.get("header_secrets", [])
        if header_secrets and source_type != "remote":
            errors.append(f"{where}: header_secrets are supported only for remote sources")
        for header_secret in header_secrets:
            if (
                not isinstance(header_secret, dict)
                or not re.fullmatch(r"[A-Za-z0-9-]+", header_secret.get("header", ""))
                or not ENV_PATTERN.fullmatch(header_secret.get("secret", ""))
            ):
                errors.append(f"{where}: invalid header secret entry")

        for env_var in server.get("environment", []):
            if (
                not isinstance(env_var, dict)
                or not ENV_PATTERN.fullmatch(env_var.get("name", ""))
                or (
                    not isinstance(env_var.get("required"), bool)
                    and not isinstance(env_var.get("value"), str)
                )
                or ("required" in env_var and "value" in env_var)
            ):
                errors.append(f"{where}: invalid environment entry")

        contract = server.get("contract")
        contract_tool_names: list[str] = []
        if contract:
            contract_path = ROOT / contract
            if contract_path.parent != ROOT / "mcp-contracts" or not contract_path.is_file():
                errors.append(f"{where}: contract must be a file under mcp-contracts/")
            else:
                contract_data = load_json(contract_path)
                contract_tool_names = [tool["name"] for tool in contract_data.get("tools", [])]
        allow_tools = server.get("allow_tools", [])
        if not isinstance(allow_tools, list) or not all(
            isinstance(tool, str) and tool for tool in allow_tools
        ):
            errors.append(f"{where}: allow_tools must contain non-empty strings")
            allow_tools = []
        if allow_tools != sorted(set(allow_tools)):
            errors.append(f"{where}: allow_tools must be unique and sorted")
        if allow_tools != contract_tool_names:
            errors.append(
                f"{where}: allow_tools must exactly match the reviewed contract tool names"
            )

        args = server.get("args", [])
        if not isinstance(args, list) or not all(isinstance(arg, str) and arg for arg in args):
            errors.append(f"{where}: args must contain non-empty strings")
        build_with = server.get("build_with", [])
        if (
            not isinstance(build_with, list)
            or not all(isinstance(item, str) and item for item in build_with)
            or (build_with and source_type != "uvx")
        ):
            errors.append(f"{where}: build_with is supported only for uvx sources")
        for volume in server.get("volumes", []):
            if (
                not isinstance(volume, dict)
                or not ENV_PATTERN.fullmatch(volume.get("host_env", ""))
                or not isinstance(volume.get("container"), str)
                or not volume["container"].startswith("/")
                or not isinstance(volume.get("read_only"), bool)
            ):
                errors.append(f"{where}: invalid volume entry")

        shared = shared_entries.get(name)
        if shared:
            expected = expected_shared_source(shared)
            if expected and source_type in {"npx", "uvx"}:
                actual = (source.get("package"), source.get("version"))
                if actual != expected:
                    errors.append(
                        f"{where}: fleet source {actual!r} differs from image manifest {expected!r}"
                    )
            elif source_type == "oci":
                image_tag = source.get("image", "").rsplit(":", 1)[-1]
                if image_tag != shared["tag"]:
                    errors.append(
                        f"{where}: OCI tag {image_tag!r} differs from image tag {shared['tag']!r}"
                    )
            if source_type != "remote":
                targets = {secret["target"] for secret in server.get("secrets", [])}
                if targets != set(shared.get("secrets", [])):
                    errors.append(
                        f"{where}: secret targets {sorted(targets)} differ from image manifest "
                        f"{sorted(shared.get('secrets', []))}"
                    )

    duplicate_names = sorted({name for name in actual_names if actual_names.count(name) > 1})
    duplicate_ports = sorted({port for port in ports if ports.count(port) > 1})
    if duplicate_names:
        errors.append(f"duplicate server names: {duplicate_names}")
    if duplicate_ports:
        errors.append(f"duplicate ports: {duplicate_ports}")
    duplicate_target_ports = sorted(
        {port for port in target_ports if target_ports.count(port) > 1}
    )
    if duplicate_target_ports:
        errors.append(f"duplicate OCI target ports: {duplicate_target_ports}")
    overlapping_ports = sorted(set(ports) & set(target_ports))
    if overlapping_ports:
        errors.append(f"OCI target ports overlap fleet proxy ports: {overlapping_ports}")
    missing_names = expected_names - set(actual_names)
    if missing_names:
        errors.append(
            "fleet is missing published repository MCPs: "
            f"missing={sorted(missing_names)}"
        )
    return errors


def source_reference(source: dict[str, Any]) -> str:
    source_type = source["type"]
    if source_type in {"npx", "uvx"}:
        return f"{source_type}://{source['package']}@{source['version']}"
    if source_type == "oci":
        return source["image"]
    return source["url"]


def workload_argv(
    fleet: dict[str, Any],
    server: dict[str, Any],
    *,
    executable: str = "thv",
    name: str | None = None,
    port: int | None = None,
    tools: list[str] | None = None,
    host: str | None = None,
    allowed_origins: list[str] | None = None,
    resolve_environment: bool = False,
    source_override: str | None = None,
) -> list[str]:
    source = server["source"]
    source_type = source["type"]
    workload_name = name or server["name"]
    workload_port = port or server["port"]
    defaults = fleet["defaults"]
    workload_host = host or defaults["host"]
    origins = allowed_origins or []
    if workload_host not in {"127.0.0.1", "localhost", "::1"} and not origins:
        raise FleetError(
            f"{server['name']}: non-loopback host {workload_host!r} requires an allowed origin"
        )
    isolate = server.get("isolate_network", defaults["isolate_network"])

    argv = [
        executable,
        "run",
        "--name",
        workload_name,
        "--group",
        fleet["group"],
        "--host",
        workload_host,
        "--proxy-port",
        str(workload_port),
        f"--isolate-network={str(isolate).lower()}",
    ]
    for origin in origins:
        argv.extend(["--allowed-origins", origin])
    if source_type in {"npx", "uvx"}:
        argv.extend(
            [
                "--transport",
                "stdio",
                "--proxy-mode",
                defaults["proxy_mode"],
                "--runtime-image",
                fleet["runtimes"][source_type],
            ]
        )
        for constraint in server.get("build_with", []):
            argv.extend(["--build-with", constraint])
    elif source_type == "oci":
        argv.extend(
            [
                "--transport",
                "streamable-http",
                "--target-port",
                str(source["target_port"]),
            ]
        )
    else:
        argv.extend(["--transport", "streamable-http"])

    if server.get("network"):
        argv.extend(["--network", server["network"]])
    if server.get("allow_docker_gateway"):
        argv.append("--allow-docker-gateway")
    for secret in server.get("secrets", []):
        argv.extend(["--secret", f"{secret['name']},target={secret['target']}"])
    for header_secret in server.get("header_secrets", []):
        argv.extend(
            [
                "--remote-forward-headers-secret",
                f"{header_secret['header']}={header_secret['secret']}",
            ]
        )
    for env_var in server.get("environment", []):
        env_name = env_var["name"]
        if "value" in env_var:
            argv.extend(["--env", f"{env_name}={env_var['value']}"])
            continue
        value = os.environ.get(env_name)
        if resolve_environment and env_var.get("required") and value is None:
            raise FleetError(f"{server['name']}: required environment variable {env_name} is unset")
        argv.extend(["--env", f"{env_name}={value if value is not None else '${' + env_name + '}'}"])
    for volume in server.get("volumes", []):
        env_name = volume["host_env"]
        host_path = os.environ.get(env_name)
        if resolve_environment and not host_path:
            raise FleetError(f"{server['name']}: volume environment variable {env_name} is unset")
        mount = f"{host_path or '${' + env_name + '}'}:{volume['container']}"
        if volume.get("read_only", True):
            mount += ":ro"
        argv.extend(["--volume", mount])
    for tool in tools if tools is not None else server.get("allow_tools", []):
        argv.extend(["--tools", tool])

    if source_override and source_type != "oci":
        raise FleetError("source overrides are supported only for OCI workloads")
    argv.append(source_override or source_reference(source))
    if server.get("args"):
        argv.append("--")
        argv.extend(server["args"])
    return argv


def selected_servers(fleet: dict[str, Any], names: list[str]) -> list[dict[str, Any]]:
    servers = fleet["servers"]
    if not names:
        return servers
    by_name = {server["name"]: server for server in servers}
    missing = sorted(set(names) - set(by_name))
    if missing:
        raise FleetError(f"unknown servers: {missing}")
    return [by_name[name] for name in names]


def render_plan(
    fleet: dict[str, Any],
    servers: list[dict[str, Any]],
    *,
    host: str | None = None,
    allowed_origins: list[str] | None = None,
) -> dict[str, Any]:
    endpoint_host = host or fleet["defaults"]["host"]
    secret_environment = sorted(
        {
            f"TOOLHIVE_SECRET_{secret_name}"
            for server in servers
            for secret_name in [
                *(secret["name"] for secret in server.get("secrets", [])),
                *(header["secret"] for header in server.get("header_secrets", [])),
            ]
        }
    )
    return {
        "schema_version": 1,
        "toolhive_version": fleet["toolhive_version"],
        "group": fleet["group"],
        "environment": {
            "TOOLHIVE_SECRETS_PROVIDER": fleet["secrets_provider"],
            "required_secret_variables": secret_environment,
        },
        "workloads": [
            {
                "name": server["name"],
                "state": server["state"],
                "endpoint": f"http://{endpoint_host}:{server['port']}/mcp",
                "contract": server.get("contract"),
                "remove_when": server.get("remove_when"),
                "argv": workload_argv(
                    fleet,
                    server,
                    host=host,
                    allowed_origins=allowed_origins,
                ),
            }
            for server in servers
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fleet", type=Path, default=DEFAULT_FLEET)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")

    plan = subparsers.add_parser("plan")
    plan.add_argument("--server", action="append", default=[])
    plan.add_argument("--format", choices=("json", "shell"), default="json")
    plan.add_argument("--host")
    plan.add_argument("--allowed-origin", action="append", default=[])

    endpoints = subparsers.add_parser("endpoints")
    endpoints.add_argument("--server", action="append", default=[])
    endpoints.add_argument("--host")

    execute = subparsers.add_parser("exec")
    execute.add_argument("--server", required=True)
    execute.add_argument("--thv-bin", default="thv")
    execute.add_argument("--name")
    execute.add_argument("--port", type=int)
    execute.add_argument("--tool", action="append")
    execute.add_argument("--host")
    execute.add_argument("--allowed-origin", action="append", default=[])
    execute.add_argument("--source-reference")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        fleet = load_fleet(args.fleet)
        errors = validate_fleet(fleet)
        if errors:
            raise FleetError("\n".join(errors))
        if args.command == "validate":
            print(
                f"PASS: {len(fleet['servers'])} MCP workloads; "
                f"{sum(server['state'] == 'ready' for server in fleet['servers'])} wrapper-free"
            )
            return 0

        requested = getattr(args, "server", [])
        servers = selected_servers(fleet, [requested] if isinstance(requested, str) else requested)
        if args.command == "plan":
            plan = render_plan(
                fleet,
                servers,
                host=args.host,
                allowed_origins=args.allowed_origin,
            )
            if args.format == "json":
                json.dump(plan, sys.stdout, indent=2)
                print()
            else:
                for workload in plan["workloads"]:
                    print(shlex.join(workload["argv"]))
            return 0
        if args.command == "endpoints":
            endpoint_host = args.host or fleet["defaults"]["host"]
            json.dump(
                {
                    server["name"]: {
                        "url": f"http://{endpoint_host}:{server['port']}/mcp",
                        "state": server["state"],
                    }
                    for server in servers
                },
                sys.stdout,
                indent=2,
            )
            print()
            return 0
        if args.command == "exec":
            server = servers[0]
            execution_env = os.environ.copy()
            execution_env.setdefault("TOOLHIVE_SECRETS_PROVIDER", fleet["secrets_provider"])
            missing_secrets = [
                f"TOOLHIVE_SECRET_{secret_name}"
                for secret_name in [
                    *(secret["name"] for secret in server.get("secrets", [])),
                    *(header["secret"] for header in server.get("header_secrets", [])),
                ]
                if not execution_env.get(f"TOOLHIVE_SECRET_{secret_name}")
            ]
            if missing_secrets:
                raise FleetError(
                    f"{server['name']}: required ToolHive secret variables are unset: "
                    f"{missing_secrets}"
                )
            argv = workload_argv(
                fleet,
                server,
                executable=args.thv_bin,
                name=args.name,
                port=args.port,
                tools=args.tool,
                host=args.host,
                allowed_origins=args.allowed_origin,
                resolve_environment=True,
                source_override=args.source_reference,
            )
            return subprocess.run(argv, check=False, env=execution_env).returncode
    except FleetError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

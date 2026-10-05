"""Disable OpenBB MCP's unconditional mutating tools at image build time."""

from pathlib import Path


def main() -> None:
    import openbb_mcp_server.app.app as app_module

    module_file = app_module.__file__
    if module_file is None:
        raise SystemExit("OpenBB app module has no source path; refusing to patch")
    path = Path(module_file)
    source = path.read_text(encoding="utf-8")
    marker = "    return mcp\n"
    if source.count(marker) != 1:
        raise SystemExit("unexpected OpenBB app.py layout; refusing to patch")
    if "register_pipeline_tool(mcp)" not in source or "async def install_skill" not in source:
        raise SystemExit("expected OpenBB mutating tool registrations were not found")
    replacement = '    mcp.disable(names=["run_pipeline", "install_skill"])\n' + marker
    path.write_text(source.replace(marker, replacement), encoding="utf-8")


if __name__ == "__main__":
    main()

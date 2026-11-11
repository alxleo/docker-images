"""Native image and MCP acceptance; live provider calls are performed after deployment."""


def test_search_decisions(docker):
    docker.host("uv", "run", "--project", "mcp-search", "--frozen", "pytest", "mcp-search/tests/", "-q")


def test_restored_oauth_expiry_in_the_installed_sdk(docker, image_ref):
    code = "import asyncio,sys; sys.path.insert(0,'/app'); from server import Account,OAuthStore; from mcp.client.auth import OAuthClientProvider; from mcp.shared.auth import OAuthClientMetadata\nasync def check():\n account=Account.model_validate({'name':'expiry','provider':'exa','billing_mode':'free','oauth':{'serverUrl':'https://mcp.exa.ai/mcp?login','clientId':'test-client','accessToken':'test-access','refreshToken':'test-refresh','expiresAt':'2020-01-01T00:00:00Z'}})\n auth=OAuthClientProvider('https://mcp.exa.ai/mcp',OAuthClientMetadata(redirect_uris=['http://127.0.0.1/callback']),OAuthStore(account))\n await auth._initialize()\n assert not auth.context.is_token_valid()\n print('restored expiry honored')\nasyncio.run(check())"
    assert "restored expiry honored" in docker.run("--entrypoint", "python", image_ref, "-c", code)


def test_native_mcp_service(docker, image_ref):
    container = docker.start(
        "-e",
        "SEARCH_MCP_TOKEN=test-search-service-token-0000000000000000",
        *docker.HARDENED,
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=16m",
        "-p",
        "18083:8080",
        image_ref,
    )
    try:
        assert (
            docker.host(
                "curl",
                "-fsS",
                "--retry",
                "15",
                "--retry-all-errors",
                "--retry-delay",
                "1",
                "http://127.0.0.1:18083/ping",
            )
            == "pong"
        )
        container.exec("python", "/app/healthcheck.py")
        output = container.exec(
            "python",
            "-c",
            "import asyncio, os, httpx2; from mcp import ClientSession; from mcp.client.streamable_http import streamable_http_client\nasync def check():\n async with httpx2.AsyncClient(headers={'Authorization':'Bearer '+os.environ['SEARCH_MCP_TOKEN']}) as http:\n  async with streamable_http_client('http://127.0.0.1:8080/mcp',http_client=http) as streams:\n   async with ClientSession(*streams) as session:\n    await session.initialize()\n    tools=await session.list_tools()\n    assert [tool.name for tool in tools.tools] == ['search']\n    result=await session.call_tool('search', {'query':''})\n    assert result.is_error\n print('native MCP discovery and invalid-input rejection passed')\nasyncio.run(check())",
        )
        assert "native MCP discovery and invalid-input rejection passed" in output
        denied = docker.host("curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://127.0.0.1:18083/mcp")
        assert denied == "401"
    finally:
        container.remove()

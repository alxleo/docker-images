"""Exercise real proxy processes and an unreachable peer on an isolated Docker network."""

import asyncio
import json
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

KEY = "native-model-discovery-fixture"
HEADERS = {"Authorization": f"Bearer {KEY}"}


async def ready(client, port, process):
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        assert process.poll() is None, f"proxy {port} exited during startup"
        try:
            response = await client.get(f"http://127.0.0.1:{port}/health/readiness", timeout=1)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(0.2)
    raise AssertionError(f"proxy {port} did not become ready")


async def qualify(directory, processes):
    backend = {
        "model_list": [{"model_name": "healthy/chat", "litellm_params": {"model": "openai/gpt-4o"}}],
        "general_settings": {"master_key": KEY},
    }
    frontend = {
        "litellm_settings": {"check_provider_endpoint": True},
        "model_list": [
            {"model_name": "subscription/chat", "litellm_params": {"model": "openai/gpt-4o"}},
            {
                "model_name": "healthy/*",
                "litellm_params": {
                    "model": "litellm_proxy/healthy/*",
                    "api_base": "http://127.0.0.1:4020",
                    "api_key": KEY,
                },
            },
            {
                "model_name": "offline/*",
                "litellm_params": {
                    "model": "litellm_proxy/offline/*",
                    "api_base": "http://" + os.environ["DISCOVERY_OFFLINE_ADDRESS"] + ":4020",
                    "api_key": KEY,
                },
            },
        ],
        "general_settings": {"master_key": KEY},
    }
    environment = os.environ | {
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "LITELLM_TELEMETRY": "False",
        "REQUEST_TIMEOUT": "10",
    }
    async with httpx.AsyncClient(trust_env=False) as client:
        for port, config in [(4020, backend), (4021, frontend)]:
            path = directory / f"{port}.json"
            path.write_text(json.dumps(config))
            log = (directory / f"{port}.log").open("w")
            process = await asyncio.to_thread(
                subprocess.Popen,
                ["/app/.venv/bin/litellm", "--config", str(path), "--host", "127.0.0.1", "--port", str(port)],
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            log.close()
            processes.append(process)
            await ready(client, port, process)

        started = time.monotonic()
        listing = asyncio.create_task(client.get("http://127.0.0.1:4021/v1/models", headers=HEADERS, timeout=7))
        await asyncio.sleep(0.2)
        health = await client.get("http://127.0.0.1:4021/health/liveliness", timeout=0.75)
        assert health.status_code == 200, health.status_code
        response = await listing
        elapsed = time.monotonic() - started
        assert response.status_code == 200, response.status_code
        names = {row["id"] for row in response.json()["data"]}
        assert {"subscription/chat", "healthy/chat"} <= names, sorted(names)
        assert not any(name.startswith("offline/") and "*" not in name for name in names), sorted(names)
        assert elapsed < 5, f"unreachable worker delayed discovery for {elapsed:.3f}s"
        print(
            json.dumps({"discovery_seconds": round(elapsed, 3), "health": health.status_code, "models": sorted(names)})
        )


with tempfile.TemporaryDirectory(prefix="litellm-discovery-") as work:
    directory = Path(work)
    processes = []
    try:
        asyncio.run(qualify(directory, processes))
    except BaseException:
        for log in directory.glob("*.log"):
            print(log.name + "\n" + log.read_text()[-6000:])
        raise
    finally:
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)

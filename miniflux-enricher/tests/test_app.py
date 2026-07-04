"""Unit tests for the Miniflux enricher — pipeline logic, no network."""

import hashlib
import hmac
import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

APP = Path(__file__).parent.parent / "app.py"


@pytest.fixture
def enricher(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "s3cr3t")
    spec = importlib.util.spec_from_file_location("enricher_app", APP)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeClient:
    """Records Miniflux PUTs; not used for LLM (that's monkeypatched at _chat)."""

    def __init__(self):
        self.puts = []

    async def put(self, url, headers=None, json=None):
        self.puts.append((url, json))


def test_hmac_verify(enricher):
    body = b'{"event_type":"new_entries"}'
    sig = hmac.new(b"s3cr3t", body, hashlib.sha256).hexdigest()
    assert enricher._verify(body, sig) is True
    assert enricher._verify(body, "deadbeef") is False


def test_looks_english(enricher):
    assert enricher._looks_english("A normal English sentence about Docker.") is True
    assert enricher._looks_english("我用 Docker Compose 管理所有的自托管服务，效果非常好。") is False
    assert enricher._looks_english("<p>Plain ascii html</p>") is True


async def _run(enricher, entry, *, verdict="KEEP", translation="TRANSLATED"):
    async def fake_chat(client, model, prompt, max_tokens):
        return verdict if model == enricher.CLASSIFY_MODEL else translation


    enricher._chat = fake_chat  # type: ignore[assignment]
    fake = _FakeClient()
    await enricher.process(fake, entry)
    return fake


@pytest.mark.asyncio
async def test_junk_is_marked_read_not_translated(enricher):
    entry = {"id": 42, "title": "10 Best VPNs You NEED in 2026", "content": "listicle", "url": "http://x/vpn"}
    client = await _run(enricher, entry, verdict="JUNK")
    # marked read via the bulk endpoint; no per-entry content write
    assert client.puts == [(f"{enricher.MINIFLUX_URL}/v1/entries", {"entry_ids": [42], "status": "read"})]
    assert enricher._metrics["junk_dropped"] >= 1


@pytest.mark.asyncio
async def test_foreign_entry_translated_in_place(enricher):
    entry = {"id": 7, "title": "中文标题", "content": "<p>中文内容</p>", "url": "http://x/a"}
    client = await _run(enricher, entry, verdict="KEEP", translation="EN")
    url, payload = client.puts[0]
    assert url == f"{enricher.MINIFLUX_URL}/v1/entries/7"
    assert payload["title"] == "EN" and payload["content"] == "EN"


@pytest.mark.asyncio
async def test_english_entry_skipped(enricher):
    entry = {"id": 9, "title": "A Rust memory leak postmortem", "content": "<p>tokio tasks</p>", "url": "http://x/b"}
    client = await _run(enricher, entry, verdict="KEEP")
    assert client.puts == []  # nothing written — English, kept


def test_webhook_rejects_bad_signature(enricher):
    from fastapi.testclient import TestClient

    with TestClient(enricher.app) as tc:
        r = tc.post("/webhook", content=b"{}", headers={"X-Miniflux-Signature": "nope"})
        assert r.status_code == 403


def test_webhook_accepts_and_acks(enricher):
    from fastapi.testclient import TestClient

    body = b'{"event_type":"new_entries","entries":[]}'
    sig = hmac.new(b"s3cr3t", body, hashlib.sha256).hexdigest()
    with TestClient(enricher.app) as tc:
        r = tc.post("/webhook", content=body, headers={"X-Miniflux-Signature": sig})
        assert r.status_code == 200

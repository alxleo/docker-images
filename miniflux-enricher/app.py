#!/usr/bin/env python3
"""Miniflux enricher — translate foreign entries + drop SEO/listicle junk, in-place.

Miniflux has no native LLM hooks, so this is the community pattern: a small
webhook worker. Miniflux fires `new_entries` (HMAC-signed); we ack in <10s
(its client timeout) and process async against the homelab's LOCAL inference
(translategemma for translation, granite4 for junk classification — free,
private, no per-item cost). Results go back in-place via the Miniflux API:
translated title+content overwrite the entry; junk is marked read so it drops
out of the unread view.

Run: INFERENCE_URL=... MINIFLUX_URL=... MINIFLUX_API_KEY=... WEBHOOK_SECRET=... \
     uv run --with fastapi --with httpx --with uvicorn uvicorn app:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response

log = logging.getLogger("enricher")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

INFERENCE_URL = os.environ.get("INFERENCE_URL", "http://inference:11434/v1")
MINIFLUX_URL = os.environ.get("MINIFLUX_URL", "http://miniflux:8080")
MINIFLUX_API_KEY = os.environ.get("MINIFLUX_API_KEY", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
TRANSLATE_MODEL = os.environ.get("TRANSLATE_MODEL", "translategemma:4b")
CLASSIFY_MODEL = os.environ.get("CLASSIFY_MODEL", "granite4:3b")
FILTER_JUNK = os.environ.get("FILTER_JUNK", "1") == "1"
WORKERS = int(os.environ.get("WORKERS", "3"))
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "120"))
CONTENT_MAX = 6000  # cap what we send to the LLM per entry

# Metrics (Prometheus text exposition; no client dep needed for a handful of counters).
_metrics = {"received": 0, "translated": 0, "junk_dropped": 0, "errors": 0, "skipped_en": 0}

_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
# Non-ASCII ratio above this ⇒ worth a language check (skips the LLM call for plain English).
_NON_ASCII = re.compile(r"[^\x00-\x7f]")
_TAG = re.compile(r"<[^>]+>")


def _verify(body: bytes, signature: str) -> bool:
    if not WEBHOOK_SECRET:
        return True  # unset ⇒ dev mode, accept (compose always sets it)
    expected = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def _looks_english(text: str) -> bool:
    """Cheap pre-filter: skip the LLM language check when the visible text is ~ASCII."""
    visible = _TAG.sub(" ", text)[:600]
    if not visible.strip():
        return True
    non_ascii = len(_NON_ASCII.findall(visible))
    return non_ascii / max(len(visible), 1) < 0.02


async def _chat(client: httpx.AsyncClient, model: str, prompt: str, max_tokens: int) -> str:
    resp = await client.post(
        f"{INFERENCE_URL}/chat/completions",
        json={"model": model, "messages": [{"role": "user", "content": prompt}],
              "max_tokens": max_tokens, "temperature": 0},
        timeout=LLM_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


async def _is_junk(client: httpx.AsyncClient, title: str, url: str) -> bool:
    """Coarse SEO/listicle classification from title+URL (cheap; content rarely needed)."""
    prompt = (
        "You are a feed quality filter. Reply with exactly one word: JUNK or KEEP.\n"
        "JUNK = listicles (\"10 best X\", \"Top 5 Y\"), content-farm/affiliate roundups, "
        "AI filler, keyword-stuffed rewrites, purely promotional posts.\n"
        "KEEP = original reporting, technical depth, opinion with a specific argument, research.\n\n"
        f"Title: {title}\nURL: {url}"
    )
    verdict = await _chat(client, CLASSIFY_MODEL, prompt, 8)
    return "JUNK" in verdict.upper()


async def _translate(client: httpx.AsyncClient, text: str, *, html: bool) -> str:
    if not text.strip():
        return text
    instruction = (
        "Translate to English. Preserve all HTML tags exactly. Output only the translated HTML."
        if html else "Translate to English. Output only the translation, no notes."
    )
    return await _chat(client, TRANSLATE_MODEL, f"{instruction}\n\n{text[:CONTENT_MAX]}", 2048)


async def _mark_read(client: httpx.AsyncClient, entry_id: int) -> None:
    await client.put(
        f"{MINIFLUX_URL}/v1/entries",
        headers={"X-Auth-Token": MINIFLUX_API_KEY},
        json={"entry_ids": [entry_id], "status": "read"},
    )


async def _write_back(client: httpx.AsyncClient, entry_id: int, title: str, content: str) -> None:
    await client.put(
        f"{MINIFLUX_URL}/v1/entries/{entry_id}",
        headers={"X-Auth-Token": MINIFLUX_API_KEY},
        json={"title": title, "content": content},
    )


async def process(client: httpx.AsyncClient, entry: dict[str, Any]) -> None:
    entry_id = entry.get("id")
    title = entry.get("title", "") or ""
    content = entry.get("content", "") or ""
    url = entry.get("url", "") or ""
    if entry_id is None:
        return

    if FILTER_JUNK and await _is_junk(client, title, url):
        await _mark_read(client, entry_id)
        _metrics["junk_dropped"] += 1
        log.info("junk-dropped %s: %s", entry_id, title[:80])
        return

    if _looks_english(f"{title} {content}"):
        _metrics["skipped_en"] += 1
        return

    new_title = await _translate(client, title, html=False)
    new_content = await _translate(client, content, html=True)
    await _write_back(client, entry_id, new_title or title, new_content or content)
    _metrics["translated"] += 1
    log.info("translated %s: %s → %s", entry_id, title[:50], new_title[:50])


async def _worker() -> None:
    async with httpx.AsyncClient() as client:
        while True:
            entry = await _queue.get()
            try:
                await process(client, entry)
            except Exception:  # noqa: BLE001 — one bad entry must not kill the worker
                _metrics["errors"] += 1
                log.exception("enrich failed for entry %s", entry.get("id"))
            finally:
                _queue.task_done()


@asynccontextmanager
async def lifespan(_: FastAPI):
    tasks = [asyncio.create_task(_worker()) for _ in range(WORKERS)]
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(lifespan=lifespan)


@app.post("/webhook")
async def webhook(request: Request) -> Response:
    body = await request.body()
    if not _verify(body, request.headers.get("X-Miniflux-Signature", "")):
        return Response(status_code=403)
    payload = await request.json()
    if payload.get("event_type") == "new_entries":
        for entry in payload.get("entries", []):
            _metrics["received"] += 1
            try:
                _queue.put_nowait(entry)
            except asyncio.QueueFull:
                _metrics["errors"] += 1
                log.warning("queue full, dropped entry %s", entry.get("id"))
    return Response(status_code=200)  # ack immediately (< Miniflux's 10s webhook timeout)


@app.get("/ping")
async def ping() -> Response:
    return Response(status_code=200)


@app.get("/metrics")
async def metrics() -> Response:
    lines = [f"enricher_{k} {v}" for k, v in _metrics.items()]
    lines.append(f"enricher_queue_depth {_queue.qsize()}")
    return Response("\n".join(lines) + "\n", media_type="text/plain")

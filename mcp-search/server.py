"""One read-only search tool over the official free hosted MCPs."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import time
from builtins import BaseExceptionGroup
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Literal

import httpx2
import uvicorn
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolResult
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from mcp import ClientSession

Provider = Literal["parallel", "exa", "tavily", "firecrawl"]
ORDER: tuple[Provider, ...] = ("parallel", "exa", "tavily", "firecrawl")
ENDPOINTS = {
    "parallel": ("https://mcp.parallel.ai/mcp?tools=web_search", "web_search"),
    "exa": ("https://mcp.exa.ai/mcp?tools=web_search_exa", "web_search_exa"),
    "tavily": ("https://mcp.tavily.com/mcp/", "tavily_search"),
    "firecrawl": ("https://mcp.firecrawl.dev/v2/mcp", "firecrawl_search"),
}
LOGIN_ENDPOINTS = {
    "exa": "https://mcp.exa.ai/mcp?login&tools=web_search_exa",
    "tavily": "https://mcp.tavily.com/mcp",
    "firecrawl": "https://mcp.firecrawl.dev/v2/mcp-oauth",
}
QUOTA_CODES = frozenset({"daily_cap_reached", "quota_exceeded", "insufficient_credits", "credit_limit_exceeded"})
QUOTA = re.compile(
    r"quota.{0,35}(?:exceed|exhaust|reach)|(?:exceed|exhaust|reach).{0,35}quota"
    r"|insufficient.{0,15}credits|credits?.{0,25}(?:exhaust|deplet|insufficient)"
    r"|usage limit|credit limit|payment required",
    re.IGNORECASE,
)
RATE = re.compile(r"rate.?limit|too many requests", re.IGNORECASE)


class OAuthSeed(BaseModel):
    """Native MCPJam OAuth credential export; only public OAuth clients are supported."""

    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    accessToken: SecretStr
    refreshToken: SecretStr | None = None
    clientId: str
    expiresAt: datetime
    serverUrl: str


class Account(BaseModel):
    """A voluntarily contributed, provider-side hard-capped free account."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,47}$")
    provider: Literal["exa", "tavily", "firecrawl"]
    api_key: SecretStr | None = None
    oauth: OAuthSeed | None = Field(default=None, repr=False)
    billing_mode: Literal["free"]

    @model_validator(mode="after")
    def credential_required(self) -> Account:
        if (self.api_key is None) == (self.oauth is None):
            raise ValueError("An account needs exactly one API key or OAuth credential")
        if self.api_key is not None and not self.api_key.get_secret_value().strip():
            raise ValueError("An API key cannot be empty")
        if self.oauth is not None:
            from urllib.parse import urlsplit

            expected = urlsplit(LOGIN_ENDPOINTS[self.provider])
            actual = urlsplit(self.oauth.serverUrl)
            if (actual.scheme, actual.netloc, actual.path) != (expected.scheme, expected.netloc, expected.path):
                raise ValueError("OAuth credentials must belong to the provider's official MCP endpoint")
        return self


def accounts_from_json(value: str) -> list[Account]:
    raw = json.loads(value)
    if not isinstance(raw, list) or len(raw) > 32:
        raise ValueError("The shared pool must contain at most 32 free accounts")
    accounts = [Account.model_validate(item) for item in raw]
    if len({a.name for a in accounts}) != len(accounts):
        raise ValueError("Shared account names must be unique")
    seen: set[tuple[str, str]] = set()
    result = []
    for account in accounts:
        identity = (
            account.provider,
            account.api_key.get_secret_value()
            if account.api_key
            else (account.oauth.refreshToken or account.oauth.accessToken).get_secret_value(),
        )
        if identity not in seen:
            seen.add(identity)
            result.append(account)
    return result


@dataclass
class Slot:
    provider: Provider
    name: str
    credential: Account | None = field(default=None, repr=False)
    until: float = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


def account_fingerprint(account: Account) -> str:
    material = account.model_dump_json()
    if account.api_key:
        material += account.api_key.get_secret_value()
    elif account.oauth:
        material += account.oauth.accessToken.get_secret_value()
        material += account.oauth.refreshToken.get_secret_value() if account.oauth.refreshToken else ""
    return hashlib.sha256(material.encode()).hexdigest()


def make_slots(accounts: list[Account]) -> list[Slot]:
    return [
        slot
        for provider in ORDER
        for slot in [
            *(Slot(provider, a.name, a) for a in accounts if a.provider == provider),
            Slot(provider, "anonymous"),
        ]
    ]


def arguments_for(provider: Provider, query: str, objective: str, max_results: int) -> dict:
    if provider == "parallel":
        return {"objective": objective, "search_queries": [query]}
    if provider == "exa":
        return {"query": query, "objective": objective, "numResults": max_results}
    if provider == "tavily":
        return {"query": query, "max_results": max_results, "search_depth": "basic"}
    return {"query": query, "objective": objective, "limit": max_results, "domainTools": False}


def retry_seconds(value: str | None, *, now: datetime | None = None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - (now or datetime.now(UTC))).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(1, min(seconds, 86400 * 31))


def quota_failure(
    status: int | None, message: str, *, is_error: bool, retry_after: str | None = None
) -> tuple[str, float] | None:
    """Search content mentioning quotas is never itself a failure."""
    if not is_error:
        return None
    if status == 402 or QUOTA.search(message):
        return "quota_exhausted", retry_seconds(retry_after) or 3600
    if status == 429 or RATE.search(message):
        return "rate_limited", retry_seconds(retry_after) or 60
    return None


def result_failure(result: CallToolResult) -> tuple[str, float] | None:
    structured = result.structured_content
    if structured is None:
        for block in result.content:
            text = getattr(block, "text", "")
            if text.startswith("{") and len(text) < 8192:
                try:
                    structured = json.loads(text)
                except ValueError:
                    continue
                if isinstance(structured, dict):
                    break
    failed = result.is_error or isinstance(structured, dict) and structured.get("success") is False
    message = " ".join(getattr(c, "text", "") for c in result.content)
    if isinstance(structured, dict):
        if structured.get("code") in QUOTA_CODES:
            seconds = retry_seconds(str(structured.get("retry_after_seconds", ""))) or 3600
            return "quota_exhausted", seconds
        message += " " + json.dumps(structured.get("error", ""))
    return quota_failure(None, message, is_error=bool(failed))


def exception_failure(exc: BaseException) -> tuple[str, float] | None:
    if isinstance(exc, BaseExceptionGroup):
        failures = [exception_failure(child) for child in exc.exceptions]
        return next((failure for failure in failures if failure is not None), None)
    if isinstance(exc, httpx2.HTTPStatusError):
        return quota_failure(
            exc.response.status_code, "", is_error=True, retry_after=exc.response.headers.get("retry-after")
        )
    if isinstance(exc, MCPError):
        return quota_failure(exc.error.code, exc.error.message, is_error=True)
    return None


def credential_headers(slot: Slot) -> dict[str, str]:
    if not slot.credential:
        return {"X-Tavily-Access-Mode": "keyless"} if slot.provider == "tavily" else {}
    if slot.credential.api_key is None:
        return {}
    key = slot.credential.api_key.get_secret_value()
    if slot.provider == "exa":
        return {"x-api-key": key}
    if slot.provider == "firecrawl":
        return {"x-firecrawl-api-key": key}
    return {"Authorization": f"Bearer {key}"}


class OAuthStore:
    """The SDK refreshes tokens; this store keeps its refreshed state across restarts."""

    def __init__(self, account: Account) -> None:
        seed = account.oauth
        if seed is None:
            raise ValueError("OAuth seed required")
        digest = account_fingerprint(account)[:16]
        self.path = Path(os.environ.get("SEARCH_STATE_DIR", "/data")) / f"{account.name}-{digest}.json"
        self.seed = seed

    async def get_tokens(self) -> OAuthToken:
        if self.path.exists():
            value = json.loads(self.path.read_text())
        else:
            value = {
                "access_token": self.seed.accessToken.get_secret_value(),
                "refresh_token": self.seed.refreshToken.get_secret_value() if self.seed.refreshToken else None,
                "token_type": "Bearer",
                "expires_at": self.seed.expiresAt.timestamp(),
            }
        value["expires_in"] = max(0, int(value.pop("expires_at") - time.time()))
        return OAuthToken.model_validate(value)

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        value = tokens.model_dump(mode="json", exclude_none=True)
        value["expires_at"] = time.time() + value.pop("expires_in", 3600)
        temporary = self.path.with_suffix(".tmp")
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as stream:
            json.dump(value, stream)
        temporary.replace(self.path)

    async def get_client_info(self) -> OAuthClientInformationFull:
        return OAuthClientInformationFull(client_id=self.seed.clientId, token_endpoint_auth_method="none")

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        if client_info.client_id != self.seed.clientId or client_info.client_secret:
            raise ValueError("Reconnect this account using a public OAuth client")


async def reconnect_required(_url: str) -> None:
    raise ValueError("The shared account requires OAuth reconnection")


async def preserve_quota_status(response: httpx2.Response) -> None:
    # The SDK otherwise discards HTTP quota status and Retry-After during JSON-RPC normalization.
    if response.status_code in (402, 429):
        response.raise_for_status()


async def call_provider(slot: Slot, arguments: dict) -> CallToolResult:
    url, tool = ENDPOINTS[slot.provider]
    auth = None
    if slot.credential and slot.credential.oauth:
        url = LOGIN_ENDPOINTS[slot.provider]
        auth = OAuthClientProvider(
            server_url=url,
            client_metadata=OAuthClientMetadata(
                redirect_uris=["http://127.0.0.1/callback"], token_endpoint_auth_method="none"
            ),
            storage=OAuthStore(slot.credential),
            redirect_handler=reconnect_required,
        )
    async with (
        httpx2.AsyncClient(
            headers=credential_headers(slot),
            auth=auth,
            timeout=20,
            event_hooks={"response": [preserve_quota_status]},
        ) as http,
        streamable_http_client(url, http_client=http) as streams,
        ClientSession(*streams) as session,
    ):
        await session.initialize()
        result = await session.call_tool(tool, arguments, read_timeout_seconds=20)
        if not isinstance(result, CallToolResult):
            raise TypeError("The search provider did not return a completed result")
        return result


class SearchPool:
    def __init__(self, accounts: list[Account]) -> None:
        self.slots = make_slots(accounts)

    def reload(self, accounts: list[Account]) -> None:
        def identity(slot: Slot) -> str:
            material = account_fingerprint(slot.credential) if slot.credential else "anonymous"
            return f"{slot.provider}:{slot.name}:{material}"

        previous = {identity(slot): slot for slot in self.slots}
        self.slots = [previous.get(identity(slot), slot) for slot in make_slots(accounts)]

    async def search(
        self, query: str, objective: str, max_results: int, preferred_provider: Provider | None = None
    ) -> dict:
        attempts = []
        slots = (
            sorted(self.slots, key=lambda slot: slot.provider != preferred_provider)
            if preferred_provider
            else self.slots
        )
        async with asyncio.timeout(100):
            for slot in slots:
                async with slot.lock:
                    if slot.until > time.monotonic():
                        attempts.append({"provider": slot.provider, "account": slot.name, "status": "cooldown"})
                        continue
                    try:
                        result = await call_provider(slot, arguments_for(slot.provider, query, objective, max_results))
                    except Exception as exc:  # noqa: BLE001 - the SDK groups exceptions from several transports
                        failure = exception_failure(exc)
                        if failure is None:
                            raise ValueError(
                                f"{slot.provider} search failed; no quota exhaustion was confirmed"
                            ) from None
                    else:
                        failure = result_failure(result)
                        if failure is None:
                            if (
                                result.is_error
                                or isinstance(result.structured_content, dict)
                                and result.structured_content.get("success") is False
                            ):
                                raise ValueError(f"{slot.provider} returned a search error unrelated to quota")
                            return {
                                "provider": slot.provider,
                                "account": slot.name,
                                "attempts": attempts,
                                "content": [block.model_dump(mode="json", by_alias=True) for block in result.content],
                                "data": result.structured_content,
                            }
                    reason, cooldown = failure
                    slot.until = time.monotonic() + cooldown
                    attempts.append(
                        {
                            "provider": slot.provider,
                            "account": slot.name,
                            "status": reason,
                            "retry_after_seconds": cooldown,
                        }
                    )
        return {"error": "All free search allowances are currently unavailable", "attempts": attempts}


def configured_pool() -> SearchPool:
    path = os.environ.get("SEARCH_ACCOUNTS_FILE")
    return SearchPool(
        accounts_from_json(Path(path).read_text() if path else os.environ.get("SEARCH_ACCOUNTS_JSON", "[]"))
    )


mcp = MCPServer("automatic-search", version="0.1.0")
pool: SearchPool | None = None


def service_token() -> str:
    path = os.environ.get("SEARCH_MCP_TOKEN_FILE")
    token = Path(path).read_text().strip() if path else os.environ.get("SEARCH_MCP_TOKEN", "")
    if len(token) < 32:
        raise ValueError("A private gateway token of at least 32 characters is required")
    return token


async def require_gateway_token(request: Request, call_next):
    if request.url.path != "/ping":
        expected = f"Bearer {service_token()}"
        if not hmac.compare_digest(request.headers.get("authorization", "").encode(), expected.encode()):
            return PlainTextResponse(
                "Gateway authentication required", status_code=401, headers={"WWW-Authenticate": "Bearer"}
            )
    return await call_next(request)


@mcp.tool()
async def search(
    query: str, objective: str = "", max_results: int = 5, preferred_provider: Provider | None = None
) -> dict:
    """Search the public web using free access, switching provider/account when quota is exhausted.

    Returns the provider and its original results. Optionally prefer a provider before trying the normal pool order.
    """
    global pool
    if not query.strip() or len(query) > 2000 or len(objective) > 5000 or not 1 <= max_results <= 10:
        raise ValueError("Provide a query up to 2000 characters, an objective up to 5000 characters, and 1–10 results")
    current = configured_pool()
    if pool is None:
        pool = current
    else:
        pool.reload([slot.credential for slot in current.slots if slot.credential])
    result = await pool.search(query, objective or query, max_results, preferred_provider)
    if "error" in result:
        raise ValueError(json.dumps(result))
    return result


@mcp.custom_route("/ping", methods=["GET"], include_in_schema=False)
async def ping(_request: Request) -> PlainTextResponse:
    return PlainTextResponse("pong")


if __name__ == "__main__":
    pool = configured_pool()
    service_token()
    hostname = os.environ.get("SEARCH_HOSTNAME", "localhost")
    app = mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=["127.0.0.1:*", "localhost:*", hostname],
            allowed_origins=[f"https://{hostname}"],
        ),
    )
    app.add_middleware(BaseHTTPMiddleware, dispatch=require_gateway_token)
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("MCP_PORT", "8080")))

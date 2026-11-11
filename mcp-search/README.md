# Automatic free search

| Priority | Free search pool |
| --- | --- |
| 1 | Parallel anonymous |
| 2 | Exa contributed accounts, then anonymous |
| 3 | Tavily contributed accounts, then anonymous |
| 4 | Firecrawl contributed accounts, then anonymous |

| Input | Behavior |
| --- | --- |
| `query`, optional `objective`, `max_results`, `preferred_provider` | One read-only search; optionally prefer a provider before the default order; result count is passed where supported |
| Provider quota error, including an MCP error inside HTTP 200 | Try the next account/provider and report the attempts |
| HTTP 429 / rate-limit error | Cool down that slot, honoring `Retry-After` |
| Other errors | Return an error; do not silently change the request |
| All slots unavailable | MCP tool error with the attempted slots |

`SEARCH_ACCOUNTS_FILE` is a secret JSON array, read on each search so the native
secret owner can add, rotate or remove accounts without restarting the service.
Unchanged slots retain their cooldown and OAuth state. `SEARCH_ACCOUNTS_JSON`
also supports a static environment configuration. Each
entry contributes an account to **one shared pool**. Duplicate API keys/tokens
are deduplicated. People must contribute accounts voluntarily, with the provider
on its free plan and paid overage/automatic top-ups disabled. `billing_mode`
must be `free`; this declaration does not change the provider's billing settings.

| Account fields | Required value |
| --- | --- |
| `name` | Unique lower-case account label |
| `provider` | `exa`, `tavily` or `firecrawl` |
| `billing_mode` | `free` |
| `api_key` **or** `oauth` | API key, or the native MCPJam `oauth login --credentials-out` export from a public OAuth client |

For OAuth, use the provider's official MCP endpoint: Exa's `/mcp?login`, Tavily's
`/mcp`, or Firecrawl's `/v2/mcp-oauth`. The public-client export needs `serverUrl`,
`clientId`, `accessToken`, `refreshToken` and `expiresAt`. Use the native secret
owner to store it; never paste credentials into an agent chat. The MCP SDK
refreshes OAuth tokens and stores refreshed state under `SEARCH_STATE_DIR`
(default `/data`), which must be persistent, private and writable by UID 1000.
Removing an account stops its selection after the secret file updates. Revoke
its provider connection separately when withdrawing that grant. The gateway
continues to own user admission; this server has no independent user enrollment.
`SEARCH_MCP_TOKEN_FILE` (or `SEARCH_MCP_TOKEN`) holds the private upstream bearer
token, at least 32 characters, so reaching the backend directly grants no access.
`SEARCH_HOSTNAME` selects the backend Host/Origin accepted by the native SDK.

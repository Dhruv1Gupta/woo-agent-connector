# WooCommerce Read-Only Connector for Agent Studio

A small, dependency-free (Python 3.9+ stdlib only) connector that lets an AI agent **read orders and
products/inventory** from a WooCommerce store through an **MCP tool server**.

| Requirement | Where |
|---|---|
| Auth flow (API key + WooCommerce app-authorization flow) | `woo_connector/auth.py`, `config.py` |
| list / get / search primitives | `woo_connector/tools.py` (8 tools) |
| Rate-limit handling | `woo_connector/client.py`, `ratelimit.py` |
| MCP tool specification | `mcp/tool_spec.json` + live `tools/list` |
| What the agent can / cannot do | `docs/AGENT_CAPABILITIES.md` |
| Tests + end-to-end demo | `tests/`, `scripts/demo.py` |

## Quick start (no store needed)

```bash
python -m unittest discover -s tests -t .  # 20 tests against a fake WooCommerce API
python scripts/demo.py   # end-to-end agent-style walkthrough
```

## Connect a real store

1. In WP admin: **WooCommerce > Settings > Advanced > REST API > Add key**. Permissions: **Read** only.
2. Provide credentials, either way:
   ```bash
   export WOOCOMMERCE_URL=https://your-store.example.com
   export WOOCOMMERCE_CONSUMER_KEY=ck_...
   export WOOCOMMERCE_CONSUMER_SECRET=cs_...
   # or: python -m woo_connector save-keys   (prompts, stores ~/.woo_connector/credentials.json, chmod 600)
   ```
3. Verify: `python -m woo_connector check`
4. Run as an MCP server: `python -m woo_connector serve`

### Authorization-flow option (merchant approves in their browser)
WooCommerce has a built-in app-authorization endpoint (`/wc-auth/v1/authorize`) that generates a
key pair and POSTs it to your callback.
```bash
python -m woo_connector auth-url --store https://shop.example.com --callback https://<public-https-host>/callback
python -m woo_connector auth-server --store https://shop.example.com --user-id <printed id> --port 8787
```
The `user_id` doubles as a one-time state token; the callback is rejected unless it matches and the key is `read`-only.
WooCommerce requires an HTTPS callback, so locally use a tunnel (e.g. ngrok/cloudflared) to port 8787.

## Plug into an agent runtime (MCP stdio)
```json
{ "mcpServers": { "woocommerce": {
    "command": "python", "args": ["-m", "woo_connector", "serve"],
    "cwd": "/path/to/woo-agent-connector",
    "env": { "WOOCOMMERCE_URL": "...", "WOOCOMMERCE_CONSUMER_KEY": "...", "WOOCOMMERCE_CONSUMER_SECRET": "..." } } } }
```
Tools: `list_orders`, `get_order`, `search_orders`, `list_products`, `get_product`, `search_products`,
`list_low_stock_products`, `connector_health`. Full schemas: `mcp/tool_spec.json`.

## Design decisions
- **Read-only by construction.** Only `GET` is implemented; the key is also requested with Read scope.
- **Rate limits, two layers.** A client-side token bucket (`WOO_RPS`, default 5/s) prevents the agent from
  hammering a merchant's store. Server-side `429/502/503/504` and network errors are retried up to
  `WOO_MAX_RETRIES` with `Retry-After` honoured (seconds or HTTP-date, capped at 60s) or exponential backoff + jitter.
  401/403/404 are never retried.
- **PII minimisation.** Default `mask` mode: emails/phones masked, street addresses dropped, names reduced to
  `Firstname L.`. `WOO_PII_MODE=full` is an explicit opt-in.
- **Prompt-injection hygiene.** Customer-written text (order notes, product descriptions) is HTML-stripped,
  length-capped and labelled `untrusted_text_fields`; every list response carries a notice to treat it as data.
- **Agent-readable errors.** Failures come back as MCP `isError` results with a short typed message; stack
  traces and credentials never reach the model. Inputs are validated (types, enums, ranges, ISO dates, unknown args rejected).
- **Secrets.** Env vars or a `chmod 600` file. Plain `http://` is refused for non-local stores.

## Limitations and the proper long-term fix
See `docs/AGENT_CAPABILITIES.md` ("Known limitations").

## Layout
```
woo_connector/  client.py ratelimit.py tools.py mcp_server.py auth.py config.py redact.py errors.py __main__.py
mcp/tool_spec.json   docs/AGENT_CAPABILITIES.md   tests/ (mock_woo.py, test_connector.py)   scripts/demo.py
```
All test data is fictional. No real customer data or credentials are included.

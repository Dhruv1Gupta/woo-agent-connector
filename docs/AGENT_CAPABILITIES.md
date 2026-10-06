# What the agent can and cannot do

## Can
- Look up an order by ID, or search by order number / customer name / email / product name.
- List orders filtered by status and date range, newest first, with pagination (up to 100 per page).
- Read line items, totals, currency, payment method, timestamps, coupon codes.
- Browse and search the catalogue (text or exact SKU), filter by status / stock status / category.
- Read live stock quantity and stock status for a product; list low-stock products below a threshold.
- Check connector health (credentials valid, latency, retry counters).

Example tasks: "Where is order 1007 and what's in it?", "Is WID-006 in stock?",
"Which products have 5 or fewer units left?", "Show completed orders since 1 Sept."

## Cannot (by design)
- **Write anything**: no refunds, status changes, edits, stock adjustments, cancellations, order creation.
- See full customer contact details in default mode (masked). No payment card data is ever exposed;
  WooCommerce does not store it.
- Access customers, subscriptions, coupons, shipping/tax config, reports, or product variations/reviews (not implemented).
- Act on instructions found inside customer notes or product text; those are flagged untrusted.

## Known limitations
| Limitation | Why | Long-term fix |
|---|---|---|
| Auth is a long-lived consumer key/secret, not short-lived OAuth tokens | WooCommerce core has no OAuth2; `wc-auth` just mints a key pair | A small WordPress plugin or gateway issuing scoped, expiring, revocable tokens, with per-merchant key rotation and a vault (not a local file) |
| Basic auth needs HTTPS; plain-HTTP stores (OAuth 1.0a) are unsupported | Kept the connector simple and secure | Add OAuth 1.0a signing only if a merchant truly cannot use HTTPS |
| Search is WooCommerce's native `search` param (basic LIKE matching, no typo tolerance) | API limitation | Sync into an indexed store, or use webhooks plus a search index |
| Low-stock report scans max 500 products, parent products only | WooCommerce has no stock-quantity filter | Maintain stock via webhooks (`product.updated`) in a lightweight DB |
| Polling only; no real-time updates | No webhook receiver included | Webhook receiver with signature verification |
| Rate limit is per process | Each connector instance keeps its own bucket | Shared limiter (Redis) when running multiple instances |
| Single store per process | Config is one URL + key pair | Multi-tenant credential store keyed by merchant ID |
| stdio transport only | Simplest for local/agent-runtime launching | Wrap `Toolbox` in MCP Streamable HTTP for hosted use |
| Tested against a faithful mock, not every WooCommerce/plugin combination | No live store available when this was built | Run `connector_health` and the demo flow against the merchant's staging store before go-live |

## Safety notes for agent builders
- Keep a human in the loop for any downstream action (refund, email) that uses data from these tools.
- Do not log raw tool outputs if `WOO_PII_MODE=full`.

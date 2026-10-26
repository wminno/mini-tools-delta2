# MiniTools

Tiny, fast REST API for the dev utilities every project needs: slugs, timestamps, case conversion, hashing, Base64, UUIDs. Built and operated by an autonomous AI agent (delta-2) as an experiment in whether useful software can pay for its own compute.

- Base URL: https://minitools.bigfloppy.net
- Status: https://minitools.bigfloppy.net/health
- Public stats: https://minitools.bigfloppy.net/v1/stats
- MCP endpoint: https://minitools.bigfloppy.net/mcp (streamable HTTP — add to Claude, Cursor, or any MCP client)

## Free tier

Every endpoint is free with 500 calls/day per key, no signup, no rate limit for normal human/agent traffic. Optional API keys: `GET /v1/keys` mints a free key (supports `?src=yourtag` attribution); pass `?key=...` on any call to see your usage at `GET /v1/me`.

## Endpoints

All return JSON.

- `GET /slug?text=Hello World` → `{"slug":"hello-world"}`
- `GET /ts?ts=1761380000` → ISO 8601 (omit `ts` for now). `GET /ts?iso=2026-10-25T12:00:00Z` → Unix time
- `GET /case?text=Hello World&style=camel|snake|kebab|pascal|upper|lower|title`
- `GET /hash?text=hello&algo=md5|sha1|sha256|sha512` (default sha256)
- `GET /b64?text=hello` encode / `GET /b64?b64=aGVsbG8=` decode
- `GET /uuid` → fresh UUID v4
- `GET /health` → liveness + version

## Use as an MCP server

Point your MCP client at `https://minitools.bigfloppy.net/mcp`. Listed in the official MCP registry as `net.bigfloppy.minitools/minitools`.

## Paid tiers (optional)

The free tier is deliberately generous. If your agent or service leans on MiniTools daily, supporter keys are sold via Stripe: https://buy.stripe.com/<see landing page> — same endpoints, priority lane, and you help an AI agent fund its own infrastructure.

## Open source

MIT. Source: https://github.com/wminno/mini-tools-delta2

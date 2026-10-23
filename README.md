# mini-tools — tiny utils API + landing page

A single-file, zero-dependency (Python 3 stdlib only) JSON API with six tiny
text/dev utilities, plus a static landing page. Built and operated by delta-2.

## Run

    PORT=8082 python3 server.py

Optional env vars:
- `PORT` (default 8082) — TCP listen port; bind `0.0.0.0`.
- `UDS` — optional unix socket path to ALSO serve on (used in the author's sandbox).
- `ACCESS_LOG` — access log path (default `./access.log` next to server.py).

No venv, no pip installs, no config files. Memory footprint ~15 MB. Concurrency
via threads; trivially safe behind any reverse proxy (Caddy/nginx) or direct.

## Endpoints (all GET, JSON)

| Endpoint | Params | Returns |
|---|---|---|
| `/health` | – | `{"ok": true}` |
| `/slug` | `text`, optional `sep` (`-`/`_`) | URL slug |
|  `/ts` | optional `iso` or `unix` (both directions) | unix ts, ISO8601 UTC + local |
| `/case` | `text`, `to` = `upper\|lower\|title\|camel\|snake\|kebab` | converted text |
| `/hash` | `text`, `algo` = sha1\|sha256\|sha512\|md5 | hex digest |
| `/b64` | `text`, `op` = `encode\|decode` | base64 result |
| `/uuid` | optional `n` (1–50) | UUID v4 list |

Static: `/` (landing page), `/sitemap.xml`, `/9cb22c4190e7c8b6.txt` (IndexNow key).

CORS: `Access-Control-Allow-Origin: *` on all API responses — callable from any
browser frontend. Errors are JSON `{"error": "..."}` with proper 4xx codes.

## Examples

    curl 'http://localhost:8082/slug?text=Hello%20World%21'
    curl 'http://localhost:8082/case?text=user%20name&to=camel'
    curl 'http://localhost:8082/hash?text=abc&algo=sha256'
    curl 'http://localhost:8082/b64?text=hello&op=encode'
    curl 'http://localhost:8082/uuid?n=5'

## Monetization

Stripe checkout links ($1 / $3) on the landing page pay the operator's wallet.
The API itself is free while usage is small; heavier tiers will be metered later.

## License

MIT

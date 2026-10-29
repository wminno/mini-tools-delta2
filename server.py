#!/usr/bin/env python3
"""delta-2 public tool server — serves over a unix socket for cloudflared."""
import os, re, socket, urllib.parse, unicodedata, json, hashlib, base64, uuid, time, threading
from datetime import datetime, timezone

SOCK = "/tmp/app.sock"
HERE = os.path.dirname(os.path.abspath(__file__))

import secrets

# --- free API keys (usage signal + future paid tiers) ---
KEYS_FILE = os.environ.get("KEYS_FILE", os.path.join(HERE, "keys.json"))
_klock = threading.Lock()
KEYS = {}
def load_keys():
    global KEYS
    try:
        with open(KEYS_FILE) as f:
            KEYS = json.load(f)
    except Exception:
        KEYS = {}
def save_keys():
    tmp = KEYS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(KEYS, f)
    os.replace(tmp, KEYS_FILE)
def bump_key(key):
    with _klock:
        if key in KEYS:
            KEYS[key]["calls"] = KEYS[key].get("calls", 0) + 1
            d = KEYS[key].get("day") or {}
            KEYS[key]["day"] = {"d": _today(), "c": d.get("c", 0) + 1 if d.get("d") == _today() else 1}
            save_keys()
load_keys()

CLAIMS_FILE = os.environ.get("CLAIMS_FILE", os.path.join(HERE, "claims.json"))
_clock = threading.Lock()
CLAIMS = {}
def load_claims():
    global CLAIMS
    try:
        with open(CLAIMS_FILE) as f:
            CLAIMS = json.load(f)
    except Exception:
        CLAIMS = {}
def save_claims():
    tmp = CLAIMS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(CLAIMS, f)
    os.replace(tmp, CLAIMS_FILE)
def new_claim():
    with _clock:
        code = "pay_" + secrets.token_hex(6)
        CLAIMS[code] = {"created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "used": False}
        save_claims()
    return code
load_claims()

def ensure_claim_pool():
    # keep a pool of unredeemed day-pass claim codes ready, so the $1 rung
    # (Stripe link -> buyer gets code -> /v1/claim) is always fulfilable.
    with _clock:
        need = 3 - sum(1 for c in CLAIMS.values() if not c.get("used"))
        if need > 0:
            for _ in range(need):
                code = "pay_" + secrets.token_hex(6)
                CLAIMS[code] = {"created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "used": False}
            save_claims()

def slugify(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:80] or "slug"

TOOL_PATHS = {"/slug", "/ts", "/case", "/hash", "/b64", "/uuid"}

# --- usage tiers (honest ladder) ---
# no key: 30 calls/day per client IP | free key: 500/day | paid day-pass: unlimited
NOKEY_DAILY = 30
FREE_DAILY = 500
STRIPE_URL = "https://buy.stripe.com/9B600k0q62XS23b8ka8Vi0g"
_ipcalls = {}
_qlock = threading.Lock()

def _today():
    return time.gmtime().tm_yday

def ip_allow(ip):
    with _qlock:
        e = _ipcalls.get(ip)
        if not e or e[0] != _today():
            e = _ipcalls[ip] = [_today(), 0]
        e[1] += 1
        return e[1] <= NOKEY_DAILY

def key_calls_today(key):
    k = KEYS.get(key) or {}
    d = k.get("day") or {}
    return d.get("c", 0) if d.get("d") == _today() else 0

def key_paid(key):
    k = KEYS.get(key) or {}
    return time.time() < k.get("paid_until", 0)

def mint_key(email="", src=""):
    with _klock:
        if len(KEYS) > 20000:
            return None
        key = "mt_" + secrets.token_hex(16)
        KEYS[key] = {"created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     "email": (email or "")[:120], "src": re.sub(r"[^A-Za-z0-9_-]", "", (src or ""))[:24], "calls": 0}
        save_keys()
    return key

def handle(method, path, ip="-"):
    p0, _, qs0 = path.partition("?")
    key = ""
    if p0 in TOOL_PATHS:
        for kv in qs0.split("&"):
            if kv.startswith("key="):
                key = urllib.parse.unquote(kv[4:].replace("+", " "))
                break
        if key and key not in KEYS:
            return 401, b'{"error":"unknown API key - mint one free at /v1/keys"}', "application/json"
        if key:
            if not key_paid(key) and key_calls_today(key) >= FREE_DAILY:
                return 429, json.dumps({"error": "free tier limit reached (500 calls/day)",
                                        "upgrade": STRIPE_URL, "note": "paid day-pass keys are unlimited"}).encode(), "application/json"
        else:
            if not ip_allow(ip):
                return 429, json.dumps({"error": "no-key limit reached (30 calls/day per IP)",
                                        "fix": "mint a free key: GET /v1/keys (500 calls/day)",
                                        "mcp": "from an MCP client, call the get_api_key tool",
                                        "upgrade": STRIPE_URL}).encode(), "application/json"
    code, body, ctype = _dispatch(method, path)
    if key and code == 200:
        bump_key(key)
    return code, body, ctype

def _dispatch(method, path):
    path, _, qs = path.partition("?")
    q = {}
    for kv in qs.split("&"):
        if "=" in kv:
            k, _, v = kv.partition("=")
            q[k] = urllib.parse.unquote(v.replace("+", " "))
    if path == "/" or path == "/index.html":
        return 200, open(os.path.join(HERE, "index.html"), "rb").read(), "text/html; charset=utf-8"
    if path == "/robots.txt":
        return 200, b"User-agent: *\nAllow: /\nSitemap: https://minitools.bigfloppy.net/sitemap.xml\n", "text/plain"
    if path == "/9cb22c4190e7c8b6.txt":
        return 200, b"9cb22c4190e7c8b6", "text/plain"
    if path == "/.well-known/mcp-registry-auth":
        return 200, open(os.path.join(HERE, "mcp-registry-auth"), "rb").read(), "text/plain; charset=utf-8"
    if path == "/.well-known/server.json":
        return 200, open(os.path.join(HERE, "server.json"), "rb").read(), "application/json"
    if path in ("/.well-known/mcp/server-card.json", "/.well-known/mcp.json"):
        return 200, _card_json(), "application/json"
    if path == "/sitemap.xml":
        x = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://minitools.bigfloppy.net/</loc><changefreq>daily</changefreq></url></urlset>'
        return 200, x.encode(), "application/xml"
    if path == "/health":
        return 200, b'{"ok":true}', "application/json"
    if path == "/slug":
        t = q.get("text", "")
        if not t:
            return 400, b'{"error":"missing ?text="}', "application/json"
        out = json.dumps({"slug": slugify(t)})
        return 200, out.encode(), "application/json"
    if path == "/ts":
        if "iso" in q:
            try:
                dt = datetime.fromisoformat(q["iso"].replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                out = json.dumps({"unix": int(dt.timestamp()), "utc": dt.astimezone(timezone.utc).isoformat()})
            except ValueError:
                return 400, b'{"error":"bad iso"}', "application/json"
        elif "unix" in q:
            try:
                dt = datetime.fromtimestamp(int(float(q["unix"])), timezone.utc)
                out = json.dumps({"iso": dt.isoformat().replace("+00:00", "Z")})
            except (ValueError, OSError, OverflowError):
                return 400, b'{"error":"bad unix"}', "application/json"
        else:
            return 400, b'{"error":"need ?iso= or ?unix="}', "application/json"
        return 200, out.encode(), "application/json"

    if path == "/case":
        t = q.get("text", "")
        style = (q.get("to", "") or "").lower()
        if not t or not style:
            return 400, b'{"error":"need ?text= and ?to=camel|snake|kebab|pascal|upper|lower|title"}', "application/json"
        def words(s):
            s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
            s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
            return re.findall(r"[a-z0-9]+", s.lower())
        w = words(t)
        if style in ("upper", "lower", "title"):
            out = {"result": t.upper() if style == "upper" else t.lower() if style == "lower" else t.title()}
        elif style == "camel" and w:
            out = {"result": w[0] + "".join(x.capitalize() for x in w[1:])}
        elif style == "pascal" and w:
            out = {"result": "".join(x.capitalize() for x in w)}
        elif style in ("snake", "kebab") and w:
            out = {"result": ("_" if style == "snake" else "-").join(w)}
        else:
            return 400, b'{"error":"unknown ?to= or empty text"}', "application/json"
        return 200, json.dumps(out).encode(), "application/json"

    if path == "/hash":
        t = q.get("text", "")
        algo = (q.get("algo", "sha256") or "sha256").lower().replace("-", "")
        if algo not in ("md5", "sha1", "sha256", "sha512"):
            return 400, b'{"error":"algo must be md5, sha1, sha256 or sha512"}', "application/json"
        if t == "":
            return 400, b'{"error":"missing ?text="}', "application/json"
        h = hashlib.new(algo, t.encode("utf-8")).hexdigest()
        return 200, json.dumps({"algo": algo, "hex": h}).encode(), "application/json"

    if path == "/b64":
        t = q.get("text", "")
        op = (q.get("op", "encode") or "encode").lower()
        if t == "":
            return 400, b'{"error":"missing ?text="}', "application/json"
        if op == "encode":
            out = {"result": base64.b64encode(t.encode("utf-8")).decode("ascii")}
            return 200, json.dumps(out).encode(), "application/json"
        if op == "decode":
            try:
                dec = base64.b64decode(t, validate=True).decode("utf-8")
            except Exception:
                return 400, b'{"error":"not valid base64"}', "application/json"
            return 200, json.dumps({"result": dec}).encode(), "application/json"
        return 400, b'{"error":"op must be encode or decode"}', "application/json"

    if path == "/uuid":
        try:
            n = min(max(int(q.get("n", "1")), 1), 50)
        except ValueError:
            return 400, b'{"error":"?n= must be an integer"}', "application/json"
        return 200, json.dumps({"uuids": [str(uuid.uuid4()) for _ in range(n)]}).encode(), "application/json"

    if path == "/v1/keys":
        key = mint_key(q.get("email", ""), q.get("src", ""))
        if key is None:
            return 429, b'{"error":"too many keys minted, try later"}', "application/json"
        out = json.dumps({"key": key, "free_tier": "500 calls/day per key", "no_key": "30 calls/day per IP",
                          "usage": "pass ?key=" + key + " on any endpoint", "status_url": "/v1/me?key=" + key,
                          "upgrade": STRIPE_URL})
        return 200, out.encode(), "application/json"
    if path == "/v1/claim":
        ensure_claim_pool()
        ck = (q.get("claim", "") or "").strip()
        with _klock:
            c = CLAIMS.get(ck)
            if not c or c.get("used"):
                return 404, json.dumps({"error": "unknown or already-used claim code"}).encode(), "application/json"
            c["used"] = True
            c["claimed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            save_claims()
            k = KEYS.get(c.get("key"))
            if k is not None:
                k["paid_until"] = time.time() + 86400
                save_keys()
                out_key = c.get("key")
            else:
                # pool claim with no bound key: mint a fresh paid key inline
                # (never call mint_key here — it re-locks _klock and deadlocks)
                if len(KEYS) > 20000:
                    out_key = None
                else:
                    out_key = "mt_" + secrets.token_hex(16)
                    KEYS[out_key] = {"created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                     "email": "", "src": "daypass", "calls": 0,
                                     "paid_until": time.time() + 86400}
                    save_keys()
                    c["key"] = out_key
                    save_claims()
        if out_key is None:
            return 500, json.dumps({"error": "key minting temporarily unavailable"}).encode(), "application/json"
        return 200, json.dumps({"ok": True, "key": out_key, "unlimited_until": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400)),
                          "note": "day-pass active on this key for 24h"}).encode(), "application/json"
    if path == "/v1/stats":
        with _klock:
            mints = len(KEYS)
            total = sum(k.get("calls", 0) for k in KEYS.values())
            srcs = {}
            for k in KEYS.values():
                s = k.get("src") or "direct"
                srcs[s] = srcs.get(s, 0) + 1
        with _anonlock:
            anon = {"total": _anon["calls"],
                    "endpoints": {p: dict(v) for p, v in sorted(_anon["paths"].items())}}
        with _clock:
            claims_open = sum(1 for c in CLAIMS.values() if not c.get("used"))
            claims_used = sum(1 for c in CLAIMS.values() if c.get("used"))
        return 200, json.dumps({"mints": mints, "total_calls": total, "mint_sources": srcs, "claims_open": claims_open, "claims_used": claims_used,
                                "anonymous_calls": anon,
                                "note": "anonymous_calls = raw requests incl. bots/health-adjacent paths; endpoints.calls are all hits, ips are unique client IPs (x-forwarded-for)"}).encode(), "application/json"
    if path == "/v1/me":
        key = q.get("key", "")
        with _klock:
            k = KEYS.get(key)
            if k is None:
                return 401, b'{"error":"unknown API key"}', "application/json"
            return 200, json.dumps({"calls": k.get("calls", 0), "calls_today": key_calls_today(key),
                                    "created": k.get("created"), "tier": "paid" if key_paid(key) else "free",
                                    "free_limit": FREE_DAILY, "upgrade": STRIPE_URL}).encode(), "application/json"
    return 404, b'{"error":"not found"}', "application/json"


# --- MCP server (streamable HTTP, JSON-RPC) at /mcp ---
TOOLS = [
 {"name":"slug","description":"Convert text to a clean, URL-safe slug (unicode/accent aware).","inputSchema":{"type":"object","properties":{"text":{"type":"string","description":"Text to slugify"}},"required":["text"]}},
 {"name":"ts","description":"Convert ISO-8601 timestamp to Unix, or Unix to ISO-8601.","inputSchema":{"type":"object","properties":{"iso":{"type":"string","description":"ISO-8601 timestamp, e.g. 2026-10-20T20:00:00Z"},"unix":{"type":"number","description":"Unix seconds to convert to ISO"}}}},
 {"name":"case","description":"Convert text to camelCase, snake_case, kebab-case, PascalCase, UPPER, lower or Title.","inputSchema":{"type":"object","properties":{"text":{"type":"string"},"to":{"type":"string","enum":["camel","snake","kebab","pascal","upper","lower","title"]}},"required":["text","to"]}},
 {"name":"hash","description":"MD5 / SHA-1 / SHA-256 / SHA-512 hex digest of a string.","inputSchema":{"type":"object","properties":{"text":{"type":"string"},"algo":{"type":"string","enum":["md5","sha1","sha256","sha512"],"default":"sha256"}},"required":["text"]}},
 {"name":"b64","description":"Base64-encode or decode a string.","inputSchema":{"type":"object","properties":{"text":{"type":"string"},"op":{"type":"string","enum":["encode","decode"]}},"required":["text","op"]}},
 {"name":"get_api_key","description":"Mint a free API key for this server's HTTP API (500 calls/day, no signup). Optional email for usage stats. Pass the key as ?key= on any HTTP endpoint.","inputSchema":{"type":"object","properties":{"email":{"type":"string","description":"Optional contact email"}}}},
 {"name":"uuid","description":"Generate 1-50 random v4 UUIDs.","inputSchema":{"type":"object","properties":{"n":{"type":"integer","minimum":1,"maximum":50,"default":1}}}},
]

SERVER_CARD = {
    "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
    "version": "1.2.2",
    "protocolVersion": "2025-06-18",
    "title": "MiniTools",
    "serverInfo": {"name": "net.bigfloppy.minitools/minitools", "title": "MiniTools", "version": "1.2.2"},
    "description": "Tiny devtools MCP server: slugs, timestamps, case conversion, hashing, base64, UUIDs. HTTP API: 30 calls/day per IP keyless, 500/day with a free key (get_api_key tool), $1 unlimited day-pass.",
    "transport": {"type": "streamable-http", "url": "https://minitools.bigfloppy.net/mcp"},
    "capabilities": {"tools": {}},
    "authentication": {"type": "none"},
    "tools": [t["name"] for t in TOOLS],
    "websiteUrl": "https://minitools.bigfloppy.net/",
}

def _card_json():
    c = dict(SERVER_CARD)
    c["tools"] = [t["name"] for t in TOOLS]
    return json.dumps(c).encode()

def mcp_call(name, args):
    qs = urllib.parse.urlencode({k: str(v) for k, v in (args or {}).items()})
    code, body, _ = handle("GET", "/%s?%s" % (name, qs))
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        data = {"raw": body.decode("utf-8", "replace")}
    return code, data

def handle_mcp(method, raw, ip="-"):
    def J(o):
        return json.dumps(o).encode("utf-8")
    if method == "OPTIONS":
        return 204, b"", "application/json"
    if method != "POST":
        return 405, J({"jsonrpc":"2.0","id":None,"error":{"code":-32000,"message":"MCP endpoint requires POST (streamable HTTP JSON-RPC)"}}), "application/json"
    try:
        req = json.loads(raw)
        assert isinstance(req, dict)
    except Exception:
        return 400, J({"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":"Parse error"}}), "application/json"
    rid = req.get("id")
    m = req.get("method", "")
    def reply(res, code=200):
        return code, J({"jsonrpc":"2.0","id":rid,"result":res}), "application/json"
    if m == "initialize":
        return reply({"protocolVersion": (req.get("params") or {}).get("protocolVersion", "2025-03-26"),
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": "minitools", "version": "1.2.2",
                                     "description": "Tiny devtools API (slug, timestamps, case, hash, base64, uuid) run by an autonomous AI agent"}})
    if m.startswith("notifications/"):
        return 202, b"", "application/json"
    if m == "tools/list":
        return reply({"tools": TOOLS})
    if m == "tools/call":
        p = req.get("params") or {}
        name = p.get("name", "")
        if not any(t["name"] == name for t in TOOLS):
            return 200, J({"jsonrpc":"2.0","id":rid,"error":{"code":-32602,"message":"Unknown tool: %s" % name}}), "application/json"
        if name == "get_api_key":
            a = p.get("arguments") or {}
            key = mint_key(a.get("email", ""), src="mcp")
            if key is None:
                return reply({"content": [{"type": "text", "text": json.dumps({"error": "too many keys minted, try later"})}], "isError": True})
            return reply({"content": [{"type": "text", "text": json.dumps({"key": key, "free_tier": "500 calls/day",
                "usage": "pass ?key=" + key + " on any HTTP endpoint e.g. https://minitools.bigfloppy.net/slug?text=Hi&key=" + key,
                "status_url": "/v1/me?key=" + key})}]})
        if not ip_allow(ip):
            return reply({"content": [{"type": "text", "text": json.dumps({"error": "free limit reached (30 calls/day per client IP without a key)",
                "fix": "call the get_api_key tool once, then pass ?key=... on HTTP endpoints (500 calls/day)",
                "upgrade": STRIPE_URL})}], "isError": True})
        code, data = mcp_call(name, p.get("arguments") or {})
        return reply({"content": [{"type": "text", "text": json.dumps(data)}], "isError": code != 200})
    if m == "ping":
        return reply({})
    return 200, J({"jsonrpc":"2.0","id":rid,"error":{"code":-32601,"message":"Method not found: %s" % m}}), "application/json"

LOG = os.environ.get("ACCESS_LOG", os.path.join(HERE, "access.log"))
_loglock = threading.Lock()
_anonlock = threading.Lock()
_anon = {"calls": 0, "paths": {}, "ips": {}}

def anon_track(target, ip):
    p = target.split("?")[0]
    with _anonlock:
        _anon["calls"] += 1
        d = _anon["paths"].setdefault(p, {"calls": 0, "ips": 0})
        d["calls"] += 1
        ips = _anon["ips"].setdefault(p, set())
        if ip not in ips and len(ips) < 5000:
            ips.add(ip)
            d["ips"] = len(ips)

def log_hit(method, target, code, ip="-"):
    if target.split("?")[0] == "/health":
        return  # watchdog noise
    anon_track(target, ip)
    try:
        with _loglock:
            with open(LOG, "a") as f:
                f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {ip} {target.split('?')[0]} {method} {code}\n")
    except Exception:
        pass

def serve(sock):
    while True:
        c, _ = sock.accept()
        with c:
            try:
                c.settimeout(5)
                req = c.recv(65536).decode("utf-8", "replace")
                line = req.split("\r\n")[0] if req else ""
                parts = line.split()
                method = parts[0] if parts else "GET"
                target = parts[1] if len(parts) > 1 else "/"
                # drain full body when Content-Length is set (POST /mcp)
                hdr, _, bodytxt = req.partition("\r\n\r\n")
                mcl = re.search(r"content-length:\s*(\d+)", hdr.lower())
                if mcl:
                    need = int(mcl.group(1)) - len(bodytxt)
                    while need > 0:
                        chunk = c.recv(min(need, 65536)).decode("utf-8", "replace")
                        if not chunk:
                            break
                        bodytxt += chunk
                        need -= len(chunk)
                ip = "-"
                for h in req.split("\r\n")[1:]:
                    if h.lower().startswith("x-forwarded-for:"):
                        ip = h.split(":", 1)[1].split(",")[0].strip() or "-"
                        break
                if target.split("?")[0] == "/mcp":
                    code, body, ctype = handle_mcp(method, bodytxt, ip)
                else:
                    code, body, ctype = handle(method, target, ip)
                log_hit(method, target, code, ip)
                reason = {200:"OK",400:"Bad Request",404:"Not Found"}.get(code,"OK")
                acao = "Access-Control-Allow-Headers: Content-Type, Accept, MCP-Session-Id\r\n" if target.split("?")[0] == "/mcp" else ""
                hdr = (f"HTTP/1.1 {code} {reason}\r\nContent-Type: {ctype}\r\n"
                       f"Access-Control-Allow-Origin: *\r\n"
                       f"Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n{acao}"
                       f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n")
                c.sendall(hdr.encode() + body)
            except Exception:
                pass

def main():
    port = int(os.environ.get("PORT", "8082"))
    uds = os.environ.get("UDS", "")
    t = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    t.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    t.bind(("0.0.0.0", port)); t.listen(64)
    print(f"listening on :{port} tcp", flush=True)
    if uds:
        try: os.unlink(uds)
        except FileNotFoundError: pass
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(uds); os.chmod(uds, 0o777); s.listen(64)
        threading.Thread(target=serve, args=(s,), daemon=True).start()
    serve(t)

if __name__ == "__main__":
    ensure_claim_pool()
    main()

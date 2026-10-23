#!/usr/bin/env python3
"""delta-2 public tool server — serves over a unix socket for cloudflared."""
import os, re, socket, urllib.parse, unicodedata, json, hashlib, base64, uuid, time, threading
from datetime import datetime, timezone

SOCK = "/tmp/app.sock"
HERE = os.path.dirname(os.path.abspath(__file__))

def slugify(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:80] or "slug"

def handle(method, path):
    path, _, qs = path.partition("?")
    q = {}
    for kv in qs.split("&"):
        if "=" in kv:
            k, _, v = kv.partition("=")
            q[k] = urllib.parse.unquote(v.replace("+", " "))
    if path == "/" or path == "/index.html":
        return 200, open(os.path.join(HERE, "index.html"), "rb").read(), "text/html; charset=utf-8"
    if path == "/9cb22c4190e7c8b6.txt":
        return 200, b"9cb22c4190e7c8b6", "text/plain"
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

    return 404, b'{"error":"not found"}', "application/json"

LOG = os.environ.get("ACCESS_LOG", os.path.join(HERE, "access.log"))
_loglock = threading.Lock()
def log_hit(method, target, code):
    if target.split("?")[0] == "/health":
        return  # watchdog noise
    try:
        with _loglock:
            with open(LOG, "a") as f:
                f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {method} {target.split('?')[0]} {code}\n")
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
                code, body, ctype = handle(method, target)
                log_hit(method, target, code)
                reason = {200:"OK",400:"Bad Request",404:"Not Found"}.get(code,"OK")
                hdr = (f"HTTP/1.1 {code} {reason}\r\nContent-Type: {ctype}\r\n"
                       f"Access-Control-Allow-Origin: *\r\n"
                       f"Access-Control-Allow-Methods: GET, OPTIONS\r\n"
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
    main()

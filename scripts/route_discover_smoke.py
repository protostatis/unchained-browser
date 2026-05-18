#!/usr/bin/env python3
"""Smoke test route_discover and enable-JS retry browser routing."""
from __future__ import annotations

import http.server
import json
import os
import socketserver
import subprocess
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _resolve_bin() -> Path:
    env = os.environ.get("UNBROWSER_BIN")
    if env:
        return Path(env)
    rel = REPO / "target" / "release" / "unbrowser"
    if rel.exists():
        return rel
    return REPO / "target" / "debug" / "unbrowser"


BIN = _resolve_bin()

HTML = """<!doctype html>
<html><head><title>Route discovery smoke</title></head><body>
  <header><nav>
    <a href="/models">Models</a>
    <a href="/about/allstars">Allstars program</a>
    <a href="/search">Search</a>
  </nav></header>
  <main>
    <form action="/search" method="get">
      <label for="q">Search catalog</label>
      <input id="q" name="q" type="search">
      <button type="submit">Search</button>
    </form>
  </main>
</body></html>"""

RETRY = """<!doctype html>
<html><head><title>Google Search</title></head><body>
  <a href="/httpservice/retry/enablejs">Retry with JavaScript</a>
  <div id="SG_REL">Having trouble accessing Search?</div>
</body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = RETRY if self.path.startswith("/retry") else HTML
        b = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *_):
        pass


def main() -> int:
    httpd = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    p = subprocess.Popen(
        [str(BIN)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    def call(method: str, **params):
        assert p.stdin is not None
        assert p.stdout is not None
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}) + "\n")
        p.stdin.flush()
        out = json.loads(p.stdout.readline())
        if "error" in out:
            raise AssertionError(out["error"])
        return out.get("result")

    ok = True

    def check(label: str, condition: bool):
        nonlocal ok
        status = "PASS" if condition else "FAIL"
        print(f"  {status}  {label}")
        if not condition:
            ok = False

    call("navigate", url=base + "/", exec_scripts=False)
    routes = call("route_discover", goal="find sentiment analysis model updated March 2023", limit=20)
    inferred = routes.get("inferred_urls", [])
    forms = routes.get("forms", [])
    visible_routes = routes.get("routes", [])

    check("route_discover returns visible routes", any(r.get("url") == base + "/models" for r in visible_routes))
    check("route_discover returns GET form query URL", any(f.get("query_url", "").startswith(base + "/search?q=") for f in forms))
    check("route_discover infers model search URL", any(i.get("kind") == "inferred_model_search_url" and "pipeline_tag=text-classification" in i.get("url", "") for i in inferred))
    check("route_discover records provenance", all(i.get("provenance") for i in inferred[:2]))

    retry = call("navigate", url=base + "/retry", exec_scripts=False)
    route = retry.get("browser_route") or {}
    check("enable-JS retry shell browser-routes", route.get("reason") == "enable_js_interstitial")
    check("browser-route evidence is specific", "google_enablejs_retry" in route.get("evidence", []))

    call("close")
    p.communicate(timeout=2)
    httpd.shutdown()

    print("ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

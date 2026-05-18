#!/usr/bin/env python3
"""Smoke test for actionable BlockMap targets on synthetic form HTML."""
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
<html><head><title>BlockMap form smoke</title></head><body>
  <main>
    <a href="/weak">here</a>
    <a href="/products" aria-label="Browse product catalog">Catalog</a>
    <button aria-label="Open filters">Filters</button>
    <form action="/search" method="get">
      <label for="q">Search terms</label>
      <input id="q" name="q" value="laptop" placeholder="Search">
      <label>Category
        <select name="category">
          <option value="all">All</option>
          <option value="books" selected>Books</option>
        </select>
      </label>
      <input type="checkbox" name="in_stock" value="1" checked>
      <input type="password" name="password" value="secret">
      <button type="submit">Search</button>
    </form>
  </main>
</body></html>
"""


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        b = HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *_):
        pass


def main():
    httpd = socketserver.TCPServer(("127.0.0.1", 0), H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}/"

    p = subprocess.Popen(
        [str(BIN)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True
    )

    def call(method, **params):
        msg = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        p.stdin.write(json.dumps(msg) + "\n")
        p.stdin.flush()
        return json.loads(p.stdout.readline())

    nav = call("navigate", url=base, exec_scripts=False)
    blockmap = nav.get("result", {}).get("blockmap", {})
    interactives = blockmap.get("interactives", {})

    ok = True

    def check(label, condition):
        nonlocal ok
        status = "PASS" if condition else "FAIL"
        print(f"  {status}  {label}")
        if not condition:
            ok = False

    forms = interactives.get("forms", [])
    form = forms[0] if forms else {}
    controls = form.get("controls", [])
    submits = form.get("submit_candidates", [])
    preview = form.get("query_preview", {})
    link_samples = interactives.get("link_samples", [])
    button_samples = interactives.get("button_samples", [])

    check("link samples bounded and ranked", len(link_samples) <= 50 and link_samples[0].get("href") == "/products")
    check("button samples include labeled button", any(b.get("aria_label") == "Open filters" for b in button_samples))
    check("form controls include associated label", any(c.get("name") == "q" and c.get("label") == "Search terms" for c in controls))
    check("select label, options, and selected value serialized", any(c.get("name") == "category" and c.get("label") == "Category" and c.get("selected") == "books" and len(c.get("options", [])) == 2 for c in controls))
    check("submit candidate exposed", submits and submits[0].get("text") == "Search")
    check("GET query preview resolves action", preview.get("action") == base + "search")
    fields = preview.get("fields", [])
    check("query preview includes current field values", any(f.get("name") == "q" and f.get("value") == "laptop" for f in fields))
    check("query preview redacts password-like fields", any(f.get("name") == "password" and f.get("value") == "[REDACTED]" for f in fields))

    call("close")
    p.communicate(timeout=2)
    httpd.shutdown()

    print("ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

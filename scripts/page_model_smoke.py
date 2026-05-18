#!/usr/bin/env python3
"""Smoke test semantic page_model objects on synthetic pages."""
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

OBJECTS_HTML = """<!doctype html>
<html><head><title>Page model smoke</title></head><body>
  <header><nav><a href="/models">Models</a><a href="/news">News</a></nav></header>
  <main>
    <form action="/search" method="get">
      <label for="q">Search models</label>
      <input id="q" name="q" type="search" placeholder="Search">
      <input name="token" type="hidden" value="secret-token">
      <button type="submit">Search</button>
    </form>
    <section class="models">
      <article class="model-card">
        <a href="/cointegrated/rubert-tiny-sentiment-balanced"><h2>cointegrated/rubert-tiny-sentiment-balanced</h2></a>
        <p>Text Classification sentiment model for short Russian texts.</p>
        <span class="tag">text-classification</span>
        <span class="tag">sentiment</span>
        <time datetime="2023-03-20">Updated Mar 20, 2023</time>
      </article>
      <article class="news-card">
        <a href="/news/climate"><h2>Climate guide for readers</h2></a>
        <p>A simple guide to climate change causes.</p>
      </article>
    </section>
  </main>
</body></html>"""

LIMIT_HTML = """<!doctype html>
<html><head><title>Enable JavaScript</title></head><body>
  <main>Please enable JavaScript to continue. This application requires JavaScript to be enabled.</main>
</body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = LIMIT_HTML if self.path.startswith("/limit") else OBJECTS_HTML
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
    base = f"http://127.0.0.1:{port}/"
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

    call("navigate", url=base, exec_scripts=False)
    model = call("page_model", goal="find sentiment model updated March 2023", limit=20)
    objects = model.get("objects", [])
    forms = [o for o in objects if o.get("kind") == "search_form"]
    model_cards = [o for o in objects if o.get("kind") == "model_card"]
    article_cards = [o for o in objects if o.get("kind") == "article_card"]

    check("page_model returns objects", len(objects) >= 3)
    check("search form object exists", bool(forms))
    check("search form has submit action", bool(forms and forms[0].get("actions")))
    fields = (forms[0].get("fields", {}) if forms else {}).get("serializable_fields", [])
    check("password-like fields are redacted", any(f.get("name") == "token" and f.get("redacted") for f in fields))
    check("model card object exists", bool(model_cards))
    card = model_cards[0] if model_cards else {}
    check("model card has owner/model fields", card.get("fields", {}).get("owner") == "cointegrated")
    check("model card has March 2023 date", card.get("fields", {}).get("date") == "2023-03-20")
    check("model card has tags", "sentiment" in card.get("fields", {}).get("tags", []))
    check("article card object exists", bool(article_cards))
    check("objects carry provenance", all(o.get("provenance") for o in objects[:3]))
    check("actions refer to kept objects", all(not a.get("object_id") or any(o.get("id") == a.get("object_id") for o in objects) for a in model.get("actions", [])))

    call("navigate", url=base + "limit", exec_scripts=False)
    limited = call("page_model", goal="continue", limit=10)
    reasons = [l.get("reason") for l in limited.get("limitations", [])]
    check("browser-route limitation is surfaced", "enable_js_interstitial" in reasons)

    call("close")
    p.communicate(timeout=2)
    httpd.shutdown()
    print("ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

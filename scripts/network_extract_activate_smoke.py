#!/usr/bin/env python3
"""Smoke test network_extract and activate on synthetic pages."""
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

ITEMS = {
    "items": [
        {"id": 1, "name": "Alpha Jacket", "price": "$19", "url": "/p/alpha"},
        {"id": 2, "name": "Beta Jacket", "price": "$29", "url": "/p/beta"},
    ],
    "total": 2,
}

OFFERS = {
    "items": [
        {"id": "g1", "name": "Gamma Offer", "description": "Fetched after button activation"},
    ],
}

HTML = """<!doctype html>
<html><head><title>Activation smoke</title></head><body>
  <main>
    <button id="load">Load offers</button>
    <div id="out">idle</div>
    <script>
      document.getElementById('load').addEventListener('click', function() {
        document.getElementById('out').textContent = 'loading';
        fetch('/api/offers.json').then(function(r) { return r.json(); }).then(function(data) {
          document.getElementById('out').textContent = data.items[0].name;
        });
      });
    </script>
  </main>
</body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/items.json":
            self._send_json(ITEMS)
        elif self.path == "/api/offers.json":
            self._send_json(OFFERS)
        else:
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def _send_json(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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

    call("navigate", url=base + "/api/items.json", exec_scripts=False)
    extracted = call("network_extract", query="alpha jacket", limit=10)
    objects = extracted.get("objects", [])
    alpha = next((o for o in objects if o.get("title") == "Alpha Jacket"), {})
    check("network_extract finds JSON array item", bool(alpha))
    check("network_extract resolves relative URLs", alpha.get("url") == base + "/p/alpha")
    check("network_extract infers product kind", alpha.get("kind") == "product_card")
    check("network_extract records provenance", alpha.get("provenance", [{}])[0].get("source") == "network")

    model = call("page_model", goal="alpha jacket", limit=10)
    network_objects = model.get("network_objects", [])
    check("page_model attaches network_objects", any(o.get("title") == "Alpha Jacket" for o in network_objects))

    call("navigate", url=base + "/", exec_scripts=True)
    activated = call("activate", text="Load offers")
    check("activate classifies a real effect", activated.get("classification") in {"dom_changed", "network_changed"})
    check("activate observes network delta", activated.get("signals", {}).get("network_delta", 0) >= 1)
    after_extract = call("network_extract", query="gamma offer", limit=10)
    check("network_extract sees activation fetch", any(o.get("title") == "Gamma Offer" for o in after_extract.get("objects", [])))

    unsupported = call("activate", text="Definitely missing action")
    check("activate reports unsupported missing text", unsupported.get("classification") == "unsupported")

    call("close")
    p.communicate(timeout=2)
    httpd.shutdown()

    print("ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

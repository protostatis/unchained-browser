#!/usr/bin/env python3
"""Smoke test merged text and card extraction JS tools."""
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
<html><head><title>Text cards smoke</title></head><body>
  <nav>Target Phrase in navigation</nav>
  <main>
    <article>
      <h1>Useful Article</h1>
      <p>Target Phrase appears in the article body with useful surrounding context.</p>
      <script>{"noise":"Target Phrase"}</script>
    </article>
    <section class="cards">
      <article class="course-card">
        <a href="/course/alpha"><h2>Alpha Course</h2></a>
        <p>Learn alpha skills.</p>
        <span class="badge">Free Trial</span>
        <noscript>alpha.jpg</noscript>
      </article>
      <article class="recipe-card">
        <a href="/recipe/beta"><h2>Beta Dinner</h2></a>
        <p>Ready in 20 minutes.</p>
        <img alt="Dinner plate" src="beta.jpg">
      </article>
    </section>
  </main>
  <footer>Target Phrase in footer</footer>
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
        out = json.loads(p.stdout.readline())
        if "error" in out:
            raise AssertionError(out["error"])
        return out.get("result")

    call("navigate", url=base, exec_scripts=False)
    clean = call("text_clean")
    hits = call("find_text", text="Target Phrase", limit=3, context_chars=40)
    around = call("text_around", text="Target Phrase", context_chars=60)
    cards = call("extract_cards", selector="article[class$='-card']", limit=5)

    ok = True

    def check(label, condition):
        nonlocal ok
        status = "PASS" if condition else "FAIL"
        print(f"  {status}  {label}")
        if not condition:
            ok = False

    check("text_clean keeps article", "Useful Article" in clean and "article body" in clean)
    check("text_clean drops chrome", "navigation" not in clean and "footer" not in clean)
    check("find_text ranks article first", hits and hits[0].get("tag") in {"p", "article"})
    check("text_around returns useful context", "article body" in around.get("text", ""))
    titles = [c.get("title") for c in cards]
    check("extract_cards returns clean titles", "Alpha Course" in titles and "Beta Dinner" in titles)
    alpha = next((c for c in cards if c.get("title") == "Alpha Course"), {})
    check("extract_cards separates meta", "Free Trial" in alpha.get("meta", []))
    check("extract_cards omits noscript image artifacts", "alpha.jpg" not in json.dumps(cards))

    call("close")
    p.communicate(timeout=2)
    httpd.shutdown()

    print("ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

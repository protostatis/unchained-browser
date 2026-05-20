#!/usr/bin/env python3
"""Smoke test JS-aware discovery surfaces against a local page.

The fixture intentionally hides most routes from the initial HTML. Plain fetch
should only see the static route; unbrowser with script execution should see
routes added by JS property assignment, timer callbacks, and fetch JSON.
"""
from __future__ import annotations

import html.parser
import http.server
import json
import os
import socketserver
import subprocess
import threading
import urllib.request
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

INDEX_HTML = """<!doctype html>
<html><head><title>Discovery smoke</title></head><body>
  <header><a href="/pricing">Pricing</a></header>
  <main>
    <h1>Discovery smoke</h1>
    <form action="/search" method="get">
      <label>Search <input name="q" value=""></label>
      <button>Search</button>
    </form>
    <nav id="js-nav"></nav>
    <section id="api-links"></section>
    <section id="delayed-links"></section>
  </main>
  <script src="/assets/app.js"></script>
  <script>
    document.addEventListener('DOMContentLoaded', function () {
      window.mountRouteManifest(document.getElementById('js-nav'));
      fetch('/api/discovery')
        .then(function (r) { return r.json(); })
        .then(function (data) {
          window.__DISCOVERY_JSON__ = data;
          var root = document.getElementById('api-links');
          data.links.forEach(function (item) {
            var a = document.createElement('a');
            a.href = item.url;
            a.textContent = item.label;
            root.appendChild(a);
          });
        });
      setTimeout(function () {
        var a = document.createElement('a');
        a.href = '/reports/monthly';
        a.textContent = 'Monthly Reports';
        document.getElementById('delayed-links').appendChild(a);
      }, 25);
    });
  </script>
</body></html>"""

APP_JS = """
window.__ROUTE_MANIFEST__ = [
  { path: '/docs', label: 'Docs' },
  { path: '/docs/api', label: 'API Reference' },
  { path: '/changelog', label: 'Changelog' },
  { path: '/integrations/slack', label: 'Slack Integration' }
];
window.__API_ENDPOINTS__ = ['/api/v1/search', '/api/v1/accounts/:id', '/api/v1/reports'];
window.mountRouteManifest = function (root) {
  window.__ROUTE_MANIFEST__.slice(0, 3).forEach(function (route) {
    var a = document.createElement('a');
    a.href = route.path;
    a.textContent = route.label;
    root.appendChild(a);
  });
};
"""

DISCOVERY_JSON = {
    "links": [
        {"url": "/customers/alpha-case-study", "label": "Alpha Case Study"},
        {"url": "/status", "label": "System Status"},
    ],
    "api_endpoints": ["/api/private/search", "/api/private/audits"],
}


class Handler(http.server.BaseHTTPRequestHandler):
    counts: dict[str, int] = {}

    def do_GET(self):
        Handler.counts[self.path] = Handler.counts.get(self.path, 0) + 1
        if self.path == "/" or self.path.startswith("/?"):
            body = INDEX_HTML.encode()
            content_type = "text/html; charset=utf-8"
        elif self.path == "/assets/app.js":
            body = APP_JS.encode()
            content_type = "application/javascript; charset=utf-8"
        elif self.path == "/api/discovery":
            body = json.dumps(DISCOVERY_JSON).encode()
            content_type = "application/json; charset=utf-8"
        else:
            body = f"<!doctype html><title>{self.path}</title><h1>{self.path}</h1>".encode()
            content_type = "text/html; charset=utf-8"

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class HtmlSummary(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []
        self.forms: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag == "form" and attrs.get("action"):
            self.forms.append(attrs["action"])
        if tag == "script" and attrs.get("src"):
            self.scripts.append(attrs["src"])


class Unbrowser:
    def __init__(self):
        self.proc = subprocess.Popen(
            [str(BIN)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self.next_id = 0

    def call(self, method: str, **params):
        assert self.proc.stdin is not None
        assert self.proc.stdout is not None
        self.next_id += 1
        self.proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params})
            + "\n"
        )
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise AssertionError("unbrowser exited without response")
        out = json.loads(line)
        if "error" in out:
            raise AssertionError(out["error"])
        return out.get("result")

    def close(self):
        try:
            self.call("close")
        except Exception:
            pass
        try:
            self.proc.communicate(timeout=2)
        except Exception:
            self.proc.kill()


def check(label: str, condition: bool) -> bool:
    status = "PASS" if condition else "FAIL"
    print(f"  {status}  {label}")
    return condition


def hrefs(rows) -> list[str]:
    return [r.get("attrs", {}).get("href") for r in rows]


def main() -> int:
    httpd = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}/"
    ok = True

    try:
        summary = HtmlSummary()
        summary.feed(urllib.request.urlopen(base, timeout=5).read().decode())
        ok &= check("plain fetch sees only static anchor", summary.links == ["/pricing"])
        ok &= check("plain fetch sees search form", summary.forms == ["/search"])
        ok &= check("plain fetch sees app script src", summary.scripts == ["/assets/app.js"])

        ub = Unbrowser()
        try:
            ub.call("navigate", url=base, exec_scripts=False)
            no_js = hrefs(ub.call("query", selector="a[href]"))
            ok &= check("unbrowser without JS sees static anchor", no_js == ["/pricing"])

            ub.call("navigate", url=base, exec_scripts=True)
            anchors = hrefs(ub.call("query", selector="a[href]"))
            expected = {
                "/pricing",
                "/docs",
                "/docs/api",
                "/changelog",
                "/customers/alpha-case-study",
                "/status",
                "/reports/monthly",
            }
            ok &= check("JS execution discovers dynamic anchors", expected.issubset(set(anchors)))
            ok &= check("dynamic href property reflects to attribute", "/docs" in anchors)

            reflection = json.loads(
                ub.call(
                    "eval",
                    code="""
                    JSON.stringify((function () {
                      var a = document.createElement('a');
                      a.href = '/property-only';
                      var img = document.createElement('img');
                      img.src = '//cdn.example.com/image.png';
                      var div = document.createElement('div');
                      div.href = '/not-a-link';
                      var fragment = document.createElement('a');
                      fragment.href = '#details';
                      var nulled = document.createElement('a');
                      nulled.href = '/temporary';
                      nulled.href = null;
                      return {
                        attr: a.getAttribute('href'),
                        prop: a.href,
                        matches: a.matches('[href]'),
                        imgProp: img.src,
                        divAttr: div.getAttribute('href'),
                        divProp: div.href,
                        divMatches: div.matches('[href]'),
                        fragmentProp: fragment.href,
                        nulledMatches: nulled.matches('[href]')
                      };
                    })())
                    """,
                )
            )
            ok &= check("href setter writes href attribute", reflection["attr"] == "/property-only")
            ok &= check("href getter resolves against location", reflection["prop"] == base + "property-only")
            ok &= check("property-created href matches [href]", reflection["matches"] is True)
            ok &= check("protocol-relative src resolves", reflection["imgProp"] == "http://cdn.example.com/image.png")
            ok &= check("unsupported href stays expando", reflection["divAttr"] is None and reflection["divProp"] == "/not-a-link")
            ok &= check("unsupported href does not match [href]", reflection["divMatches"] is False)
            ok &= check("fragment href resolves", reflection["fragmentProp"] == base + "#details")
            ok &= check("null href removes route attribute", reflection["nulledMatches"] is False)

            stores = ub.call("network_stores", limit=10)
            store_urls = {s.get("url") for s in stores}
            ok &= check("fetch JSON is captured in network_stores", base + "api/discovery" in store_urls)

            routes = ub.call("route_discover", goal="find docs api changelog status reports", limit=20)
            route_urls = {r.get("url") for r in routes.get("routes", [])}
            ok &= check("route_discover includes JS-created route", base + "docs/api" in route_urls)
            ok &= check("route_discover includes timer-created route", base + "reports/monthly" in route_urls)

            Handler.counts.clear()
            discovery = ub.call(
                "discover",
                url=base,
                goal="find docs api changelog status reports",
                exec_scripts=True,
                same_origin=True,
                limit=20,
            )
            discovery_urls = {r.get("url") for r in discovery.get("routes", [])}
            sources_by_url = {r.get("url"): set(r.get("sources") or []) for r in discovery.get("routes", [])}
            api_urls = {e.get("url") for e in discovery.get("api_endpoints", [])}
            ok &= check("discover merges JS-created routes", base + "docs/api" in discovery_urls)
            ok &= check("discover exec_scripts navigates once", Handler.counts.get("/", 0) == 1)
            ok &= check("discover merges timer-created routes", base + "reports/monthly" in discovery_urls)
            ok &= check("discover labels static route source", "static_dom" in sources_by_url.get(base + "pricing", set()))
            ok &= check("discover labels JS route source", "js_dom" in sources_by_url.get(base + "docs/api", set()))
            ok &= check("discover extracts JSON API endpoints", base + "api/private/search" in api_urls)
            ok &= check("discover default output is compact", "navigate" not in discovery and "route_discover" not in discovery)
            ok &= check("discover includes navigate summary", bool(discovery.get("navigate_summary")))
            ok &= check("discover reports network source", discovery.get("summary", {}).get("network_sources", 0) >= 1)

            debug_discovery = ub.call("discover", url=base, goal="find pricing", debug=True, limit=5)
            ok &= check("discover debug includes nested navigate", "navigate" in debug_discovery)
            ok &= check("discover debug includes nested route_discover", "route_discover" in debug_discovery)
        finally:
            ub.close()
    finally:
        httpd.shutdown()
        httpd.server_close()

    print("ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

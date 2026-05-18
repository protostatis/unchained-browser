#!/usr/bin/env python3
"""Read-only live smoke checks for generalized agent-facing features.

This is intentionally a small, manual smoke. It hits a few unrelated public
pages to catch features that pass synthetic fixtures but fail on common real
HTML shapes. It should not be used as a deterministic CI gate because live sites
can rate-limit, change markup, or serve interstitials.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable

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


class Session:
    def __init__(self):
        self.proc = subprocess.Popen(
            [str(BIN)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )

    def call(self, method: str, **params: Any) -> Any:
        msg = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        assert self.proc.stdin is not None
        assert self.proc.stdout is not None
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("unbrowser closed without a response")
        out = json.loads(line)
        if "error" in out:
            raise RuntimeError(out["error"])
        return out.get("result")

    def close(self) -> None:
        try:
            self.call("close")
            self.proc.communicate(timeout=2)
        except Exception:
            self.proc.kill()


def check(label: str, condition: bool, details: str = "") -> bool:
    status = "PASS" if condition else "FAIL"
    suffix = f"  {details}" if details else ""
    print(f"  {status}  {label}{suffix}")
    return condition


def wikipedia_form() -> bool:
    session = Session()
    try:
        nav = session.call("navigate", url="https://www.wikipedia.org/", exec_scripts=False)
        interactives = nav.get("blockmap", {}).get("interactives", {})
        forms = interactives.get("forms") or []
        form = forms[0] if forms else {}
        controls = form.get("controls") or []
        preview = form.get("query_preview") or {}
        page_model = session.call("page_model", goal="search wikipedia encyclopedia", types=["search_form"], limit=5)
        search_forms = [o for o in page_model.get("objects", []) if o.get("kind") == "search_form"]
        labels = " ".join(str(c.get("label") or "") for c in controls)
        ok = True
        ok &= check("Wikipedia loads without challenge", nav.get("status") == 200 and not nav.get("challenge"))
        ok &= check("link samples are populated", len(interactives.get("link_samples") or []) > 10)
        ok &= check("search control is labeled", "Search" in labels)
        ok &= check("GET query preview is exposed", "search-redirect.php" in str(preview.get("action")))
        ok &= check("page_model exposes search form", bool(search_forms and search_forms[0].get("actions")))
        return ok
    finally:
        session.close()


def python_docs_text() -> bool:
    session = Session()
    try:
        session.call("navigate", url="https://docs.python.org/3/tutorial/index.html", exec_scripts=False)
        clean = session.call("text_clean", max_chars=800)
        hits = session.call("find_text", text="Using the Python Interpreter", limit=3, context_chars=60)
        around = session.call("text_around", text="Using the Python Interpreter", context_chars=120)
        ok = True
        ok &= check("text_clean keeps main document text", "The Python Tutorial" in clean)
        ok &= check("text_clean trims chrome enough", "Navigation" not in clean[:300])
        ok &= check("find_text locates section link/text", bool(hits))
        ok &= check("text_around returns local context", "Python Interpreter" in (around.get("text") or ""))
        return ok
    finally:
        session.close()


def npr_cards_and_network() -> bool:
    session = Session()
    try:
        nav = session.call("navigate", url="https://www.npr.org/sections/news/", exec_scripts=True)
        cards = session.call("extract_cards", limit=5)
        page_model = session.call("page_model", goal="news article headlines", types=["article_card"], limit=5)
        article_objects = [o for o in page_model.get("objects", []) if o.get("kind") == "article_card"]
        network = nav.get("network_stores") or {}
        source_hosts = network.get("source_hosts") or []
        ok = True
        ok &= check("NPR loads without challenge", nav.get("status") == 200 and not nav.get("challenge"))
        ok &= check("extract_cards returns news cards", len(cards) >= 3)
        ok &= check("cards include title and URL", all(c.get("title") and c.get("url") for c in cards[:3]))
        ok &= check("page_model exposes article cards", len(article_objects) >= 3)
        ok &= check("page_model article cards have provenance", all(o.get("provenance") for o in article_objects[:3]))
        ok &= check("network summary includes query hint", bool((network.get("full_query_hint") or {}).get("nav_id")))
        if network.get("count", 0) > 0:
            ok &= check("network source_hosts backs capture count", bool(source_hosts))
        else:
            print("  INFO  network capture count is 0 on this run")
        return ok
    finally:
        session.close()


def pypi_browser_route() -> bool:
    session = Session()
    try:
        nav = session.call("navigate", url="https://pypi.org/search/?q=requests", exec_scripts=False)
        route = nav.get("browser_route") or {}
        return check(
            "PyPI JS interstitial routes to browser",
            route.get("needed") is True and route.get("reason") == "enable_js_interstitial",
            str(route),
        )
    finally:
        session.close()


def reuters_challenge_report() -> bool:
    session = Session()
    try:
        nav = session.call("navigate", url="https://www.reuters.com/world/", exec_scripts=False)
        challenge = nav.get("challenge") or {}
        if challenge:
            return check("Reuters challenge is classified", bool(challenge.get("provider")), str(challenge))
        print("  INFO  Reuters did not challenge this run")
        return True
    finally:
        session.close()


def main() -> int:
    cases: list[tuple[str, Callable[[], bool]]] = [
        ("Wikipedia form discovery", wikipedia_form),
        ("Python docs text tools", python_docs_text),
        ("NPR cards and network summary", npr_cards_and_network),
        ("PyPI browser-route detection", pypi_browser_route),
        ("Reuters challenge classification", reuters_challenge_report),
    ]
    failures = 0
    for name, fn in cases:
        print(f"\n{name}")
        try:
            if not fn():
                failures += 1
        except Exception as exc:
            failures += 1
            print(f"  FAIL  unexpected error: {exc}")
    print("\nALL PASS" if failures == 0 else f"FAILURES: {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

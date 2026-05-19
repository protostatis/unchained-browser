# JS-aware info discovery plan

`unbrowser` should own the middle tier between plain fetch and full Chrome for
web-agent information discovery.

Plain fetch is cheap but only sees the initial HTML. Chrome sees the real page
graph but is too heavy to use as the default crawler. `unbrowser` can be the
cheap-first discovery layer: execute light JavaScript, observe DOM and network
changes, recover routes/forms/API surfaces, classify when the cheap path is not
enough, and hand Chrome a precise escalation target.

## Product thesis

Build `unbrowser` around this promise:

> Given a URL and a goal, discover the reachable information surface of the
> page/site, prove where each candidate came from, and say which routes need
> Chrome.

This is higher leverage than positioning the project as a tiny browser. Agents
rarely need a browser for its own sake; they need to know what information is
available, where to go next, and which tool should retrieve it.

## Target use case

Primary workflow:

1. Agent starts with a URL and task goal.
2. `unbrowser` discovers static links, forms, JS-injected routes, script route
   manifests, API endpoints, and network JSON payloads.
3. `unbrowser` ranks candidates against the goal and returns provenance for each
   candidate.
4. Agent follows cheap candidates with `unbrowser` first.
5. If a page is a JS shell, visual UI, bot wall, or heavy SPA, `unbrowser`
   returns an explicit escalation reason and the best Chrome target URL/action.

Example goal:

```json
{
  "url": "https://example.com",
  "goal": "find pricing, API docs, changelog, status, and customer case studies",
  "same_origin": true,
  "budget_ms": 10000,
  "depth": 2
}
```

Expected output:

```json
{
  "routes": [
    {
      "url": "https://example.com/docs/api",
      "label": "API Reference",
      "source": "js_dom",
      "score": 0.91,
      "provenance": [{"source": "dom", "selector": "a[href]", "ref": "e:74"}]
    }
  ],
  "forms": [],
  "api_endpoints": [],
  "network_sources": [],
  "escalations": []
}
```

## Where we are

Current main already has most of the low-level pieces needed for a discovery
product.

| Capability | Current state | Evidence |
|---|---|---|
| Cheap navigation | Built | `navigate` fetches, parses, returns BlockMap, headers, challenge, recommendations. |
| Static DOM links/forms | Built | `query`, `blockmap`, `route_discover`, form summaries, GET submit. |
| Light JS execution | Built but bounded | `navigate {exec_scripts: true}` runs inline/external scripts under watchdog. |
| Dynamic DOM observation | Partial | JS-created nodes are queryable when attributes are set via `setAttribute`; DOM property reflection is incomplete. |
| Timers/fetch settle | Built | Navigate and `settle` drain timers, microtasks, and fetches. |
| Network capture | Built | `network_stores` captures JSON/GraphQL/NDJSON/route-data responses with nav scoping. |
| Network semantic extraction | Built | `network_extract` parses captured JSON into scored objects. |
| Page-level semantic model | Built | `page_model` returns forms, cards, answer blocks, limitation objects, and network objects. |
| Route discovery | Built but narrow | `route_discover` ranks visible links/forms/query URLs. |
| Action probing | Built | `activate` classifies click effects as navigation, DOM change, network change, no effect, or unsupported. |
| Browser/challenge routing | Built for common cases | Challenge detection, tool recommendations, browser-route limitations in PageModel. |
| Regression corpus | Built | WebVoyager JSONL corpus, scorer, smoke scripts, v1-v5 runs. |

Internal demo result:

| Tool path | Routes discovered |
|---|---|
| Plain fetch of initial HTML | `/pricing` only. |
| `unbrowser` without JS | `/pricing` only. |
| `unbrowser` with JS | `/pricing`, `/docs`, `/docs/api`, `/changelog`, `/customers/alpha-case-study`, `/status`, `/reports/monthly`. |

The demo also captured `/api/discovery` in `network_stores` and exposed route
manifest/API globals via safe diagnostic `eval`.

## Current gaps

These are the gaps between the current toolset and a durable `discover` product.

| Gap | Why it matters | Current symptom |
|---|---|---|
| No unified `discover` RPC | Agents must manually sequence `navigate`, `route_discover`, `network_stores`, `network_extract`, `page_model`, and `eval`. | Capability exists but feels like a toolkit, not a product. |
| DOM property/attribute reflection incomplete | Real JS often does `a.href = url`, `img.src = url`, `input.value = x`. Discovery must see those as attributes and live properties. | Demo links set via `a.href = ...` were not found by `query('a[href]')`; `setAttribute` worked. |
| `route_discover` does not merge all discovery surfaces | It sees visible DOM routes/forms, not script literals, JS globals, captured JSON routes, or framework manifests as first-class route sources. | Route graph is incomplete unless agent writes custom eval/parsing. |
| `route_discover` scalability needs hardening | It must be safe as a default first tool on large pages. | Live HN timed out at the 30s watchdog in prior review, while synthetic smoke passed. |
| JS global discovery is manual | Route manifests often live in `__NEXT_DATA__`, `__NUXT__`, router globals, or app config. | Agent has to guess globals or run custom eval. |
| Script literal discovery is absent | Many routes/API endpoints are string literals in JS bundles even if not executed into DOM. | Fetch can see script srcs but not useful route strings; `unbrowser` does not yet summarize them. |
| Network captures are not route-normalized | Captured JSON can contain links and endpoints, but they are exposed as raw captures or semantic objects, not a route/API graph. | Agent must inspect `body_preview` or use `network_extract` and infer route candidates. |
| Action expansion is not integrated | Menus, tabs, and load-more controls may reveal routes after safe clicks. | `activate` exists, but discovery does not budget or schedule action probes. |
| Escalation targets are not precise enough for discovery | Chrome should receive the URL/action that failed cheaply, not a vague instruction. | Tool recommendations include `chrome_escalation`, but discovery does not yet emit a route-level escalation object. |
| Cross-page crawl state is missing | Discovery should support shallow site graph expansion with dedupe, budgets, and same-origin policy. | Current RPC methods operate on the current page/session; orchestration is external. |

## Where we want to get to

Target capability:

> `discover` returns a ranked, provenance-backed graph of routes, forms,
> endpoints, data sources, actions, and escalation targets for a URL/goal.

### Proposed RPC

```json
{
  "method": "discover",
  "params": {
    "url": "https://example.com",
    "goal": "find pricing docs api changelog status",
    "depth": 1,
    "same_origin": true,
    "exec_scripts": false,
    "action_budget": 3,
    "time_budget_ms": 10000,
    "route_limit": 100,
    "include_api_endpoints": true,
    "include_network_sources": true
  }
}
```

### Proposed output shape

```json
{
  "url": "https://example.com/",
  "title": "Example",
  "status": 200,
  "goal": "find pricing docs api changelog status",
  "summary": {
    "routes": 42,
    "forms": 2,
    "api_endpoints": 9,
    "network_sources": 4,
    "actions_probed": 3,
    "escalations": 1
  },
  "routes": [
    {
      "url": "https://example.com/docs/api",
      "label": "API Reference",
      "kind": "document_route",
      "source": "js_dom",
      "score": 0.93,
      "confidence": 0.88,
      "matched_terms": ["api", "docs"],
      "page_owned": true,
      "provenance": [
        {"source": "dom", "selector": "a[href]", "ref": "e:74", "reason": "JS-created visible link"}
      ]
    }
  ],
  "forms": [
    {
      "action": "https://example.com/search",
      "method": "get",
      "label": "Search form",
      "query_url": "https://example.com/search?q=pricing%20api",
      "controls": [],
      "provenance": []
    }
  ],
  "api_endpoints": [
    {
      "url": "https://example.com/api/search",
      "method": "GET",
      "source": "script_literal",
      "confidence": 0.72,
      "provenance": []
    }
  ],
  "network_sources": [
    {
      "capture_id": 3,
      "url": "https://example.com/api/discovery",
      "kind": "json",
      "object_count": 12,
      "route_count": 5,
      "body_truncated": false
    }
  ],
  "actions": [
    {
      "label": "More",
      "ref": "e:91",
      "effect": "dom_changed",
      "new_routes": 6,
      "provenance": []
    }
  ],
  "escalations": [
    {
      "url": "https://example.com/map",
      "reason": "canvas_or_map_ui",
      "confidence": 0.91,
      "recommended_tool": "chrome",
      "evidence": ["map canvas present", "no DOM result cards"]
    }
  ]
}
```

## Discovery source taxonomy

Every discovered candidate should identify one primary source and preserve all
supporting provenance.

| Source | Meaning | Examples |
|---|---|---|
| `static_dom` | Anchor/form present in initial parsed HTML. | SSR nav links, footer links, search forms. |
| `js_dom` | DOM route exists after script/timer/fetch execution. | JS menu links, route cards, API-populated lists. |
| `form_inference` | Query URL synthesized from a page-owned GET form. | `/search?q=<goal>`. |
| `script_src` | Route or endpoint found as a loaded script URL. | Next chunks, app bundles. |
| `script_literal` | URL/path string found in script contents. | `/api/v1/search`, `/docs/:slug`. |
| `js_global` | Route/API found in known globals. | `__NEXT_DATA__`, `__NUXT__`, route manifests. |
| `network_json` | Route/API found in captured JSON/GraphQL/NDJSON response. | API search results, CMS payloads. |
| `activation` | Route appeared after safe click/action probe. | Menus, tabs, load-more. |
| `sitemap` | Route found from sitemap/robots side channel. | `/sitemap.xml`, `robots.txt`. |
| `manual_hint` | Explicitly supplied by caller, not discovered. | Seed URLs, allowlisted templates. |

## Phased plan

### Phase 0: Lock the demo and baseline

Goal: make the internal discovery demo reproducible and measurable.

Tasks:

1. Add a local smoke script for the discovery demo used in this review.
2. Assert that plain fetch finds only the static link and `unbrowser` finds JS
   DOM, delayed DOM, and network-discovered links.
3. Add a fixture that uses `a.href = ...` and mark it expected-fail until DOM
   reflection is fixed.
4. Add timing assertions so discovery regressions are obvious.

Acceptance criteria:

1. `scripts/discovery_smoke.py` runs without external network.
2. It reports route counts by source: static, JS DOM, delayed DOM, network JSON.
3. It fails if network captures or JS-injected routes disappear.

### Phase 1: Fix DOM reflection for discovery-critical properties

Goal: make JS-created links/forms behave like browser DOM.

Tasks:

1. Add reflected string properties for `href`, `src`, `action`, `method`, `name`,
   `type`, `placeholder`, `title`, `alt`, `rel`, `target`, and `value` where
   appropriate.
2. Normalize getters to resolve URL-bearing properties against `location.href`
   while preserving `getAttribute()` raw values.
3. Ensure property setters call `setAttribute()` so selectors like `a[href]` work.
4. Add tests for `a.href = '/x'`, `img.src = '/i.png'`, `form.action = '/search'`,
   and `input.value = 'q'`.

Acceptance criteria:

1. The internal demo passes with `a.href = route.path`, not only
   `setAttribute('href', route.path)`.
2. `query('a[href]')` sees property-created links.
3. Dynamic script loader behavior remains unchanged.

### Phase 2: Make `route_discover` safe and fast on large pages

Goal: keep route discovery usable as a default post-navigate step.

Tasks:

1. Profile `route_discover` and `page_model` on HN, Zillow, CNBC, Wikipedia, and
   Coursera-class pages.
2. Replace broad repeated DOM walks with single-pass collection where possible.
3. Cap candidate scoring inputs before expensive text/context extraction.
4. Add per-tool JS-side budgets and return partial results with
   `limitations[]` rather than timing out the whole RPC.
5. Add live-safe smoke fixtures with thousands of links/cards.

Acceptance criteria:

1. HN `route_discover {limit: 20}` completes under 1s locally.
2. HN `page_model {limit: 20}` completes under 2s locally or returns partial
   results with a timeout limitation.
3. No route-discovery RPC hits the 30s dispatch watchdog on checked-in smoke
   pages.

### Phase 3: Build route candidate unification

Goal: produce one normalized graph from the existing tools.

Tasks:

1. Add shared route candidate schema in JS or Rust.
2. Merge candidates from DOM links, forms, `route_discover`, `network_extract`,
   and `page_model` actions.
3. Dedupe by normalized URL plus source/kind.
4. Preserve multiple provenance entries when the same route is found from DOM and
   network JSON.
5. Score candidates using goal terms, page ownership, source confidence, label
   quality, and route kind.

Acceptance criteria:

1. A route discovered from both a JS anchor and a network JSON response appears
   once with both provenance entries.
2. Same-origin filtering is applied consistently.
3. Goal-relevant routes outrank generic footer/legal routes.

### Phase 4: Add script/global discovery

Goal: recover routes hidden in scripts even when the DOM does not materialize.

Tasks:

1. Add bounded script text scanning for route-like and endpoint-like string
   literals.
2. Parse known framework stores: `__NEXT_DATA__`, RSC payload hints,
   `__NUXT__`, Remix/Astro/SvelteKit-style manifests where feasible.
3. Scan selected globals for arrays/objects with `path`, `href`, `url`, `route`,
   `endpoint`, `label`, `title`, and `name` keys.
4. Return candidates as `script_literal` or `js_global`, not as raw eval output.
5. Cap payload sizes and redact token-like values.

Acceptance criteria:

1. Next/Nuxt fixture exposes docs/product routes without custom eval.
2. Script literals identify API endpoints without including secrets or random
   asset URLs as high-confidence routes.
3. Framework discovery is bounded and does not execute page-provided strings.

### Phase 5: Normalize network discovery

Goal: turn captured JSON into routes and API surfaces automatically.

Tasks:

1. Extend `network_extract` or add a route-specific extractor over network
   captures.
2. Identify URL fields, path fields, GraphQL operation names, pagination cursors,
   and API endpoint shapes.
3. Classify candidates as `document_route`, `listing_route`, `api_endpoint`,
   `data_source`, or `pagination_route`.
4. Attach capture provenance: `capture_id`, source URL, JSON path, response kind,
   and truncation state.
5. Add `network_sources` summary to `discover`.

Acceptance criteria:

1. API-populated demo links are discovered from both rendered DOM and captured
   JSON.
2. A captured API response with route fields contributes route candidates even if
   rendering fails.
3. Truncated captures are marked lower-confidence and do not claim complete
   discovery.

### Phase 6: Integrate safe action expansion

Goal: cheaply discover routes behind menus/tabs/load-more without becoming a full
browser agent.

Tasks:

1. Rank safe action candidates from buttons, links with no href, tabs, accordions,
   menu toggles, and load-more controls.
2. Enforce an `action_budget` and skip destructive or authenticated actions.
3. Use `activate` to classify effects and collect newly visible routes/network
   captures.
4. Roll back or reload between action probes when mutations conflict.
5. Return action provenance and effect summaries.

Acceptance criteria:

1. Synthetic menu/tabs fixtures expose hidden links after activation.
2. Submit/delete/purchase/account-changing controls are never auto-activated.
3. Discovery output shows which action revealed each new route.

### Phase 7: Add the high-level `discover` RPC

Goal: make discovery a first-class product surface.

Tasks:

1. Add `discover` to JSON-RPC and MCP schemas.
2. Implement single-page discovery first: navigate, settle, collect DOM/forms,
   collect scripts/globals, collect network captures, optionally probe actions,
   merge/rank/dedupe, classify escalations.
3. Add shallow crawl support behind `depth > 1`, with same-origin filtering,
   route limits, per-host budgets, and visited URL dedupe.
4. Add `discover_route` or `continue_discover` only if a single RPC becomes too
   large for long crawls.
5. Document the cheap-first routing policy.

Acceptance criteria:

1. Demo call returns all expected static, JS, delayed, and network routes.
2. The output includes source/provenance for every candidate.
3. `discover` defaults to ultra-cheap static mode and can opt into
   `exec_scripts=true` when fetch-visible routes are insufficient.
4. `discover` emits route-level escalation objects for known browser-only pages.

### Phase 8: Measure on real discovery tasks

Goal: prove that discovery is better than fetch and cheaper than Chrome.

Tasks:

1. Create a discovery corpus separate from answer-extraction WebVoyager tasks.
2. Include docs sites, marketing sites, package/model indexes, listings, news,
   app shells, and bot/challenge pages.
3. Compare three runners: plain fetch, `unbrowser discover`, and Chrome/CDP.
4. Track route recall, useful route precision, time, memory, and escalation
   correctness.
5. Keep a small smoke corpus in repo and a larger optional external corpus.

Acceptance criteria:

1. `unbrowser discover` finds materially more goal-relevant routes than fetch on
   JS-heavy discovery fixtures.
2. Chrome is only recommended when evidence says the cheap path cannot proceed.
3. Metrics can be regenerated with one command.

## Priority order

Recommended next engineering sequence:

1. Add `scripts/discovery_smoke.py` so the concept has a permanent regression
   test.
2. Fix DOM property reflection for `href`/`src`/`action` and related fields.
3. Optimize `route_discover`/`page_model` large-page behavior.
4. Build the route candidate schema and merger.
5. Add script/global and network route extraction.
6. Wrap everything in `discover`.
7. Add shallow crawl and action expansion.
8. Build the discovery corpus and publish before/after metrics.

## Non-goals

Keep the scope tight:

1. Do not attempt visual discovery through screenshots.
2. Do not solve CAPTCHAs or behavioral challenges inside `unbrowser`.
3. Do not auto-click state-changing authenticated actions.
4. Do not replace Chrome for heavy app UIs; return precise escalation targets.
5. Do not expose secrets from scripts, globals, cookies, or network captures.

## Success metrics

Measure the product on discovery, not browser compatibility alone.

| Metric | Target |
|---|---|
| Static parity | Match fetch on static anchors/forms. |
| JS route lift | Find JS DOM/script/global/network routes fetch misses. |
| Useful precision | Goal-relevant routes rank above chrome/legal/social links. |
| Provenance coverage | 100% of candidates include source and evidence. |
| Escalation correctness | Browser-only pages route to Chrome with clear reason. |
| Runtime | Single-page discovery under 2s on normal SSR pages, bounded under configured budget on heavy pages. |
| Safety | No state-changing activation without explicit caller opt-in. |

## Open design questions

1. Should `discover` live entirely inside the Rust binary, or should a Python
   driver orchestrate multi-page depth while the binary handles single-page
   discovery?
2. Should route candidates be returned as one mixed `routes[]` list, or separated
   into `documents[]`, `api_endpoints[]`, `actions[]`, and `data_sources[]` with a
   merged `all_candidates[]` view?
3. How much JS global scanning is safe by default before it becomes too noisy or
   token-heavy?
4. Should script literal scanning fetch all same-origin bundles, or only scripts
   already fetched during `navigate {exec_scripts: true}`?
5. What is the right confidence penalty for routes found only in network/script
   data but not visible in the DOM?

## Positioning

The external story should be:

> `unbrowser` is a JS-aware discovery and routing layer for AI agents. It finds
> the information surface that fetch misses, avoids Chrome until necessary, and
> gives every candidate a source, confidence, and escalation path.

# WebVoyager usability improvement plan

Distributed implementation plan for improving `unbrowser` usability against a
fixed WebVoyager-style task set. The goal is to split the work into independent
subagent branches, merge them into one integration PR, then rerun and score the
same task corpus.

## Baseline run

Sixteen read-only WebVoyager tasks were run with subagents using only
`target/release/unbrowser` over JSON-RPC.

Raw per-task baseline records are checked in at
`docs/webvoyager-baseline-2026-05-16.jsonl`. The file intentionally stores the
subagent result summaries in JSONL rather than prose so future candidate runs can
diff task outcomes, timings, signals, and friction counters mechanically.

| Metric | Baseline |
|---|---:|
| Answer success | 11 / 16 |
| Non-bot-wall answer success | 11 / 13 |
| Correct hard challenge routing | 3 / 3 |

Failure classes:

| Class | Count | Tasks |
|---|---:|---|
| Expected bot-wall escalation | 3 | `Amazon--0`, `Booking--0`, `ESPN--18` |
| Rate-limit / soft block | 1 | `ArXiv--0` |
| Benchmark or site drift | 1 | `BBC News--28` |

Successful tasks:

| Task | Domain | Notes |
|---|---|---|
| `ArXiv--17` | arxiv.org | Direct paper page extraction worked; search path had friction. |
| `ArXiv--27` | arxiv.org | Clean SSR category page. |
| `BBC News--5` | bbc.com | Clean article extraction after direct article URL resolution. |
| `Apple--12` | apple.com | Clean SSR; noisy text required targeted extraction. |
| `Apple--6` | apple.com | Product page extraction worked. |
| `Apple--19` | apple.com | Needed embedded data / text filtering. |
| `Allrecipes--40` | allrecipes.com | Article navigation and paragraph extraction worked. |
| `Allrecipes--41` | allrecipes.com | Listing/cards worked with title cleanup. |
| `GitHub--29` | github.com | Pricing page worked; text was noisy. |
| `GitHub--37` | github.com | Product page worked; headings needed filtering. |
| `Coursera--37` | coursera.org | Large SSR/listing page was usable. |

## Target fixes

1. Add richer form summaries.
2. Add `find_text` / `text_around` style localized extraction.
3. Add cleaner content modes for main/article text.
4. Promote `aws_waf` as a first-class challenge path.
5. Surface rate-limit metadata and retry hints.
6. Make BlockMap interactive fields expandable, not just counts.
7. Improve repeated card/list extraction.
8. Record WebVoyager task runs as JSONL and score future builds consistently.

## Branch and worktree setup

Start from a single integration branch, then create subagent branches from it:

```bash
git switch -c feature/webvoyager-usability
git worktree add ../ub-agent-blockmap -b agent/blockmap-forms
git worktree add ../ub-agent-text -b agent/text-tools
git worktree add ../ub-agent-lists -b agent/list-cards
git worktree add ../ub-agent-challenge -b agent/challenge-rate-limit
git worktree add ../ub-agent-eval -b agent/webvoyager-eval
```

## Workstreams

| Agent | Fixes | Primary files | Deliverables |
|---|---|---|---|
| A: BlockMap/forms | 1, 6 | `src/js/blockmap.js`, `src/js/interact.js`, `src/js/dom.js` | Rich form summaries, expandable link/button samples, correct `select` value serialization. |
| B: Text tools | 2, 3 | `src/main.rs`, `src/js/extract.js`, `README.md` | `find_text`, `text_around`, cleaner content modes, RPC/MCP docs. |
| C: Cards/lists | 7 | `src/js/extract.js`, `src/main.rs` if needed | Cleaner `extract_list`, optional `extract_cards` / auto-card helper, dedupe/noise stripping. |
| D: Challenge/rate-limit | 4, 5 | `src/challenge.rs`, `src/main.rs`, `scripts/router.py`, `scripts/watch.py` | First-class `rate_limited` / `429` metadata, better AWS WAF router/watch behavior. |
| E: Eval runner | 8 | `train/corpus/*`, `train/*.py`, `train/README.md` | Fixed 16-task corpus, JSONL result schema, scorer comparing baseline vs candidate. |
| Integrator | All | All touched docs/tests | Merge branches, resolve API naming, run full score, open one implementation PR. |

Suggested timeboxes:

| Agent | Budget | Stop condition |
|---|---:|---|
| A: BlockMap/forms | 90 min | Smoke test demonstrates richer form summaries on a synthetic page. |
| B: Text tools | 90 min | RPC/MCP exposes localized text extraction and docs describe it. |
| C: Cards/lists | 60 min | Synthetic card/list smoke test proves cleaned titles/snippets. |
| D: Challenge/rate-limit | 60 min | Unit tests cover `429` and AWS WAF metadata/watch output. |
| E: Eval runner | 90 min | Runner can emit JSONL using the shared schema below. |
| Integrator | 120 min | All branches merged, validation run, 16-task rerun scored. |

If a subagent hits its budget before finishing, it should stop with a short
handoff note covering what landed, what failed, and the smallest remaining next
step. This prevents the distributed run from drifting into open-ended research.

## Shared API contract

Keep existing fields backward-compatible wherever possible.

BlockMap additions:

| Field | Shape |
|---|---|
| `blockmap.interactives.links` | Existing count, unchanged. |
| `blockmap.interactives.buttons` | Existing count, unchanged. |
| `blockmap.interactives.link_samples` | `[{ref, text, href, aria_label, role}]` |
| `blockmap.interactives.button_samples` | `[{ref, text, type, aria_label, role}]` |
| `blockmap.interactives.forms[]` | `{ref, action, method, enctype, fields, controls, submitters, query_preview}` |
| `forms[].controls[]` | `{ref, tag, type, name, label, placeholder, value, checked, options}` |

Text tool additions:

| RPC | Purpose |
|---|---|
| `find_text {text, selector?, exact?, limit?, context_chars?}` | Return localized text hits with context: `{ref, tag, attrs, text, before, match, after}`. |
| `text_around {text? | ref?, selector?, context_chars?}` | Return text near a known string or element ref. |
| `text_clean` or `text_main` extension | Strip `script`, `style`, `noscript`, embedded JSON, nav/footer/aside, and duplicate boilerplate. |

Challenge/rate-limit additions:

| Field | Shape |
|---|---|
| `navigate.rate_limit` | `{limited, status, retry_after, retry_after_seconds, hint}` |
| `challenge.provider` for AWS WAF | Keep `aws_waf`; ensure docs/router/watch all label it clearly. |
| `429` handling | Prefer `rate_limited` metadata over generic `unknown_block` when no vendor signature is present. |

List extraction additions:

| Area | Requirement |
|---|---|
| `extract_list` text cleanup | Ignore `script`, `style`, `noscript`; collapse whitespace; remove image fallback artifacts. |
| Card helper | Prefer common card/article/product/course selectors and return title/url/snippet/image/meta where available. |

## Shared result schema

All subagents and the eval runner should emit one JSON object per task with this
shape. Extra fields are allowed, but these keys must stay stable so scoring can
be automated.

```json
{
  "task_id": "ArXiv--17",
  "web_name": "ArXiv",
  "start_url": "https://arxiv.org/",
  "question": "Find the paper 'GPT-4 Technical Report', when was v3 submitted?",
  "success": true,
  "handled_success": true,
  "handling": "answered",
  "answer": "Mon, 27 Mar 2023 17:46:54 UTC",
  "confidence": "high",
  "steps": 15,
  "elapsed_ms": 90000,
  "unbrowser_signals": {
    "statuses": [200],
    "challenge_provider": null,
    "likely_js_filled": false,
    "rate_limit": null
  },
  "friction": {
    "eval_used": false,
    "body_used": true,
    "manual_url_guess": true,
    "noisy_text": false,
    "form_confusion": true,
    "rate_limited": false,
    "challenge_routed": false
  },
  "path_taken": ["navigate home", "submit search", "navigate abs page"],
  "failure_or_friction": "Search form selection was ambiguous."
}
```

Allowed `handling` values:

| Value | Meaning |
|---|---|
| `answered` | Task was answered directly. |
| `challenge_routed` | Task stopped on an expected challenge and exposed actionable metadata. |
| `rate_limited` | Task stopped on `429` or equivalent retry-later state. |
| `site_drift` | Benchmark target no longer exists or has materially changed. |
| `failed` | Any other failure. |

## Merge order

1. Merge Agent A first. It changes DOM/blockmap/interact internals and unblocks better form/search behavior.
2. Merge Agent C second. It changes JS extraction internals with limited API surface.
3. Merge Agent D third. Challenge/rate-limit behavior is mostly independent, and it should land before Agent B so text/search helpers can consume accurate `rate_limit` and challenge metadata instead of encoding their own retry heuristics.
4. Merge Agent B fourth. It wires final RPC/MCP API names and docs after A/C settle, and after D defines the final retry/escalation signals.
5. Merge Agent E fifth. The scorer/corpus should target the final result schema.
6. Integrator runs full tests, reruns the 16 tasks, commits final docs, and opens one implementation PR from `feature/webvoyager-usability`.

## Validation

Every subagent should run:

```bash
cargo test
cargo build --release
python3 -m unittest train.test_collect -v
```

Subagents should add local smoke scripts when useful, following the existing
`scripts/*_smoke.py` pattern with a local HTTP server instead of live network
dependencies.

## Fixed rerun corpus

Use the same tasks for baseline and candidate scoring:

| Task | Start URL | Expected handling |
|---|---|---|
| `ArXiv--17` | `https://arxiv.org/` | Answer. |
| `ArXiv--27` | `https://arxiv.org/` | Answer. |
| `ArXiv--0` | `https://arxiv.org/` | Answer or cleanly classify rate limit. |
| `BBC News--5` | `https://www.bbc.com/news/` | Answer. |
| `BBC News--28` | `https://www.bbc.com/news/` | Answer if possible; otherwise classify site drift. |
| `Apple--12` | `https://www.apple.com/` | Answer. |
| `Apple--6` | `https://www.apple.com/` | Answer. |
| `Apple--19` | `https://www.apple.com/` | Answer. |
| `Allrecipes--40` | `https://www.allrecipes.com/` | Answer. |
| `Allrecipes--41` | `https://www.allrecipes.com/` | Answer. |
| `Amazon--0` | `https://www.amazon.com/` | Correctly route `aws_waf`. |
| `Booking--0` | `https://www.booking.com/` | Correctly route `aws_waf`. |
| `GitHub--29` | `https://github.com/` | Answer. |
| `GitHub--37` | `https://github.com/` | Answer. |
| `Coursera--37` | `https://www.coursera.org/` | Answer. |
| `ESPN--18` | `https://www.espn.com/` | Correctly route `aws_waf`. |

## Scoring

Track two top-level scores:

| Score | Meaning |
|---|---|
| Answer success | The task was answered correctly. |
| Handled success | The task was answered correctly or correctly routed as expected challenge/site drift/rate-limit. |

Also track friction counters from subagent reports:

| Counter | Meaning |
|---|---|
| `eval_used` | Agent needed raw JS extraction. |
| `body_used` | Agent needed full raw HTML/body fallback. |
| `manual_url_guess` | Agent had to guess a URL instead of discovering it from page structure. |
| `noisy_text` | Text extraction included large irrelevant nav/JSON/duplicate content. |
| `form_confusion` | Agent selected the wrong form/input/submit path. |
| `rate_limited` | Site returned `429` or equivalent. |
| `challenge_routed` | Challenge was correctly surfaced without retries. |

Candidate acceptance targets:

- No regressions on the 11 successful baseline tasks.
- Preserve `3 / 3` correct `aws_waf` routing.
- Improve `ArXiv--0` from `unknown_block` to clean `rate_limited` handling, or complete it if possible without unsafe retrying.
- Reduce friction counters, especially `eval_used`, `body_used`, `manual_url_guess`, `noisy_text`, and `form_confusion`.

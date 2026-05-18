# WebVoyager Data Format

This document defines the JSONL data contract for the WebVoyager-style corpora
and completed run artifacts checked into `docs/`.

## Files

| Artifact | Purpose |
|---|---|
| `webvoyager-baseline-v{N}-YYYY-MM-DD.jsonl` | Fast-regression baseline results. |
| `webvoyager-site-coverage-v{N}.jsonl` | Corpus rows, one representative task per benchmark site. |
| `webvoyager-site-coverage-run-v{N}-YYYY-MM-DD.jsonl` | Completed all-site coverage result rows. |

All files are JSONL: one JSON object per non-empty line. Consumers must tolerate
extra fields and absent optional fields because run artifacts are audit records,
not migrations of older measurements.

Legacy artifacts may contain batch-level or normalized timestamps shared by
multiple rows. Treat those as run provenance, not per-task timing. New artifacts
should prefer per-task end timestamps plus a shared `run_id`.

## Corpus Rows

Corpus rows must include:

| Field | Type | Meaning |
|---|---|---|
| `task_id` | string | Stable task identifier. |
| `web_name` | string | Site label. |
| `start_url` | string | Initial URL. |
| `question` | string | Read-only task prompt. |
| `expected_handling` | string, optional | Expected outcome class when known. |

## Result Rows

Result rows should use this schema. Optional fields are marked explicitly; all
other fields are required by `train/webvoyager_eval.py validate`.

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | string, optional | Preferred value for new rows: `webvoyager-result-v1`. |
| `run_id` | string | Shared identifier for all rows from one execution batch. |
| `run_timestamp` | string | ISO-8601 task end time. Use real run-end time for new rows. UTC rollover between local start and end is valid. |
| `task_id` | string | Matches a corpus row. |
| `web_name` | string | Site label. |
| `start_url` | string | Initial URL. |
| `question` | string | Task prompt. |
| `success` | boolean | True only when the task was answered directly. |
| `handled_success` | boolean | True when the task was answered or correctly routed/classified. |
| `handling` | string | One of the allowed handling values below. |
| `answer` | string or null, optional | Final answer or partial finding. May be present when `success=false` for site drift or routed cases. |
| `confidence` | number or string | Preferred for new rows: number from 0.0 to 1.0. Legacy baseline rows use `high`, `medium`, `low`, or `none`. |
| `steps` | integer, optional | Count of meaningful agent actions. Challenge-only routes may be low because no usable interactives were exposed. |
| `elapsed_ms` | integer, optional | Observed time until answer or classification. Timeout-capped values should set `timed_out=true` when known. |
| `timed_out` | boolean, optional | True when `elapsed_ms` is a timeout cap instead of normal completion time. |
| `unbrowser_signals` | object | Runtime signals used for answer/routing decisions. |
| `friction` | object | Boolean friction counters. |
| `path_taken` | array | Human-readable action strings. Prefer `verb URL` when a URL is known. |
| `failure_or_friction` | string or null | Null or absent when there is no issue. Empty strings are invalid. |

Allowed `handling` values:

| Value | Meaning |
|---|---|
| `answered` | Task was answered directly. |
| `challenge_routed` | Task stopped on an expected challenge and exposed actionable metadata. |
| `rate_limited` | Task stopped on `429` or equivalent retry-later state. |
| `browser_routed` | Strict `unbrowser` cannot serve the required rendered/canvas/JS UI; use a browser. |
| `site_drift` | Benchmark target no longer exists or has materially changed. |
| `failed` | Any other failure. |

## Runtime Signals

`unbrowser_signals` should use these stable keys when present:

| Field | Type | Meaning |
|---|---|---|
| `statuses` | array of integers | HTTP statuses observed on primary navigations. |
| `challenge_provider` | string or null | Canonical provider label such as `aws_waf`, `cloudflare_turnstile`, `datadome`, or `unknown_block`. Do not mix retry state into this field. |
| `challenge` | object or null | Full challenge detector result. `clearance_cookie` must be a cookie-name hint or null, never a live cookie value. |
| `rate_limit` | object or null | Retry-later metadata. |
| `browser_route` | object or null | Strict-mode browser-routing decision. |
| `likely_js_filled` | boolean | BlockMap density indicated an SSR shell or JS-filled surface. |
| `network_captures` | integer, optional | Count of captured JSON/API responses considered. |
| `network_objects` | integer, optional | Count of semantic network objects extracted. |
| `page_model_summary` | object, optional | Counts of semantic page-model objects. |
| `activation_classification` | string, optional | `activate` result class, for example `navigated` or `no_effect`. |
| `route_discover_used` | boolean, optional | Whether page-owned route discovery informed the answer/path. |
| `route_discover_summary` | object, optional | Counts and top route-discovery evidence. |
| `route_provenance` | object or array, optional | Evidence that a route came from visible links/forms/page-owned data. |

Challenge envelope:

```json
{
  "blocked": true,
  "provider": "aws_waf",
  "confidence": 0.99,
  "status": 202,
  "matched": ["aws-waf-token"],
  "clearance_cookie": null,
  "reason": "aws_waf challenge",
  "hint": "Needs browser clearance cookie."
}
```

Checked-in artifacts must not store live clearance cookie values. If a run sees a
cookie value, replace it with the cookie name, a redacted marker, or null before
committing the JSONL.

Rate-limit envelope:

```json
{
  "limited": true,
  "status": 429,
  "retry_after": "120",
  "retry_after_seconds": 120,
  "hint": "Stop or retry later; do not spin retries."
}
```

Browser-route envelope:

```json
{
  "needed": true,
  "reason": "enable_js_interstitial",
  "confidence": 0.95,
  "evidence": ["/httpservice/retry/enablejs"],
  "hint": "Use a managed browser or another rendered source."
}
```

## Friction Counters

`friction` keys are booleans. Missing keys count as false.

| Field | Meaning |
|---|---|
| `eval_used` | Agent needed raw JS evaluation. |
| `body_used` | Agent needed full raw HTML/body fallback. |
| `manual_url_guess` | Agent guessed a URL not provenanced to page-owned links/forms/data. |
| `noisy_text` | Text extraction contained large irrelevant nav/JSON/duplicate content. |
| `form_confusion` | Agent selected the wrong form/input/submit path. |
| `rate_limited` | Site returned `429` or equivalent. |
| `challenge_routed` | Challenge was surfaced without unsafe retries. |
| `browser_routed` | Task required rendered browser behavior in strict mode. |

`manual_url_guess` should be true when the agent constructs or uses a URL that
was not supported by a visible link, form action, script-discovered route,
network response, or `route_discover` provenance. It should remain false for
absolute or relative URLs copied from page-owned links/forms, URLs returned by
captured first-party APIs, query URLs generated from a discovered form action,
or routes with explicit `route_provenance` evidence.

For v1-v4 artifacts, interpret `manual_url_guess` as the friction observed by
that run's available tools. `route_discover` provenance is only present in v5+, so
some older guesses may become page-provenanced in later runs.

## Artifact Changelog

| Artifact | Format notes |
|---|---|
| `webvoyager-baseline-v1-2026-05-16.jsonl` | Legacy fast-regression baseline. Uses string `confidence`; has no `schema_version`; `rate_limit` may be null or an object. |
| `webvoyager-site-coverage-run-v1-2026-05-17.jsonl` | Introduces all-site result rows, numeric `confidence`, and `browser_routed` friction. |
| `webvoyager-site-coverage-run-v2-2026-05-17.jsonl` | Adds `browser_route` metadata. |
| `webvoyager-site-coverage-run-v3-2026-05-17.jsonl` | Adds `page_model_summary`. |
| `webvoyager-site-coverage-run-v4-2026-05-17.jsonl` | Adds challenge envelope, network extraction counts, and activation classification. |
| `webvoyager-site-coverage-run-v5-2026-05-17.jsonl` | Adds route-discovery usage, summary, and provenance fields. |

## Scoring Notes

Answer success and handled success are separate by design. AWS WAF tasks and
browser-required Google/Wolfram tasks may be handled successfully without being
answered. Do not remove them from the corpus silently; report them as
`challenge_routed` or `browser_routed` so strict-mode limitations remain visible.

#!/usr/bin/env python3
"""Score WebVoyager-style JSONL task runs.

The scorer intentionally operates on completed result logs only. It validates
that a run covers the supplied corpus and prints aggregate metrics that can be
compared across local subagent runs.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional


REQUIRED_CORPUS_KEYS = {
    "task_id",
    "web_name",
    "start_url",
    "question",
}

REQUIRED_RESULT_KEYS = {
    "run_id",
    "task_id",
    "run_timestamp",
    "web_name",
    "start_url",
    "question",
    "success",
    "handled_success",
    "handling",
    "confidence",
    "unbrowser_signals",
    "friction",
}

KNOWN_HANDLING_VALUES = {
    "answered",
    "browser_routed",
    "challenge_routed",
    "rate_limited",
    "site_drift",
    "failed",
}

LEGACY_CONFIDENCE_VALUES = {
    "high",
    "medium",
    "low",
    "none",
}

FRICTION_KEYS = [
    "eval_used",
    "body_used",
    "manual_url_guess",
    "noisy_text",
    "form_confusion",
    "rate_limited",
    "challenge_routed",
    "browser_routed",
]


class ValidationIssue(Exception):
    """Raised when validation errors make scoring unsafe."""

    def __init__(self, errors: list[str], warnings: list[str]):
        super().__init__("validation failed")
        self.errors = errors
        self.warnings = warnings


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open() as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_no}: expected JSON object")
            rows.append(row)
    return rows


def _duplicate_ids(rows: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for row in rows:
        task_id = row.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            continue
        if task_id in seen and task_id not in duplicates:
            duplicates.append(task_id)
        seen.add(task_id)
    return duplicates


def _validate_confidence(label: str, value: Any, errors: list[str]) -> None:
    if isinstance(value, bool):
        errors.append(f"result {label} confidence must be a number in [0, 1] or legacy label")
    elif isinstance(value, (int, float)):
        if not 0.0 <= value <= 1.0:
            errors.append(f"result {label} confidence out of range: {value!r}")
    elif isinstance(value, str):
        if value not in LEGACY_CONFIDENCE_VALUES:
            errors.append(f"result {label} has unknown legacy confidence: {value!r}")
    else:
        errors.append(f"result {label} confidence must be a number in [0, 1] or legacy label")


def validate(corpus: list[dict[str, Any]], results: list[dict[str, Any]]) -> None:
    errors: list[str] = []
    warnings: list[str] = []

    if not corpus:
        errors.append("corpus is empty")

    for idx, row in enumerate(corpus, start=1):
        missing = sorted(REQUIRED_CORPUS_KEYS - row.keys())
        if missing:
            errors.append(f"corpus row {idx} missing keys: {', '.join(missing)}")

    for task_id in _duplicate_ids(corpus):
        errors.append(f"corpus has duplicate task_id: {task_id}")
    for task_id in _duplicate_ids(results):
        errors.append(f"results have duplicate task_id: {task_id}")

    corpus_ids = {row.get("task_id") for row in corpus if isinstance(row.get("task_id"), str)}
    result_ids = {row.get("task_id") for row in results if isinstance(row.get("task_id"), str)}

    for task_id in sorted(corpus_ids - result_ids):
        errors.append(f"missing result for corpus task_id: {task_id}")
    for task_id in sorted(result_ids - corpus_ids):
        warnings.append(f"result task_id not in corpus: {task_id}")

    for idx, row in enumerate(results, start=1):
        missing = sorted(REQUIRED_RESULT_KEYS - row.keys())
        label = row.get("task_id") or f"row {idx}"
        if missing:
            errors.append(f"result {label} missing keys: {', '.join(missing)}")
        if "run_id" in row and (not isinstance(row.get("run_id"), str) or not row.get("run_id")):
            errors.append(f"result {label} run_id must be a non-empty string")
        handling = row.get("handling")
        if handling not in KNOWN_HANDLING_VALUES:
            errors.append(f"result {label} has unknown handling: {handling!r}")
        if "confidence" in row:
            _validate_confidence(str(label), row.get("confidence"), errors)
        if "success" in row and not isinstance(row.get("success"), bool):
            errors.append(f"result {label} success must be boolean")
        if "handled_success" in row and not isinstance(row.get("handled_success"), bool):
            errors.append(f"result {label} handled_success must be boolean")
        if "friction" in row and not isinstance(row.get("friction"), dict):
            errors.append(f"result {label} friction must be an object")
        if "failure_or_friction" in row:
            value = row.get("failure_or_friction")
            if value == "":
                errors.append(f"result {label} failure_or_friction must be null or non-empty string")
            elif value is not None and not isinstance(value, str):
                errors.append(f"result {label} failure_or_friction must be null or string")

    if errors or warnings:
        if errors:
            raise ValidationIssue(errors, warnings)
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)


def _percent(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "0.0%"
    return f"{(numerator / denominator) * 100:.1f}%"


def _friction_counts(rows: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        friction = row.get("friction")
        if not isinstance(friction, dict):
            continue
        for key in FRICTION_KEYS:
            if friction.get(key) is True:
                counts[key] += 1
    return counts


def score(corpus: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]:
    validate(corpus, results)

    result_by_id = {row["task_id"]: row for row in results if row.get("task_id")}
    scored_rows = [result_by_id[row["task_id"]] for row in corpus if row.get("task_id") in result_by_id]
    total = len(corpus)
    answer_success = sum(1 for row in scored_rows if row.get("success") is True)
    handled_success = sum(1 for row in scored_rows if row.get("handled_success") is True)
    handling_counts = Counter(str(row.get("handling")) for row in scored_rows)
    friction_counts = _friction_counts(scored_rows)

    per_site: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "tasks": 0,
        "answer_success": 0,
        "handled_success": 0,
        "handling": Counter(),
        "friction": Counter(),
    })
    site_order: list[str] = []
    for task in corpus:
        site = str(task["web_name"])
        if site not in site_order:
            site_order.append(site)
        row = result_by_id.get(task["task_id"])
        bucket = per_site[site]
        bucket["tasks"] += 1
        if not row:
            continue
        if row.get("success") is True:
            bucket["answer_success"] += 1
        if row.get("handled_success") is True:
            bucket["handled_success"] += 1
        bucket["handling"][str(row.get("handling"))] += 1
        bucket["friction"].update(_friction_counts([row]))

    return {
        "total": total,
        "answer_success": answer_success,
        "handled_success": handled_success,
        "handling_counts": handling_counts,
        "friction_counts": friction_counts,
        "per_site": [(site, per_site[site]) for site in site_order],
    }


def _format_counter(counter: Counter[str]) -> str:
    if not counter:
        return "-"
    return ", ".join(f"{key}={counter[key]}" for key in sorted(counter))


def print_score(summary: dict[str, Any]) -> None:
    total = summary["total"]
    answer_success = summary["answer_success"]
    handled_success = summary["handled_success"]

    print(f"tasks: {total}")
    print(f"answer success: {answer_success}/{total} ({_percent(answer_success, total)})")
    print(f"handled success: {handled_success}/{total} ({_percent(handled_success, total)})")

    print("\nhandling counts:")
    for handling, count in sorted(summary["handling_counts"].items()):
        print(f"  {handling}: {count}")

    print("\nfriction totals:")
    friction_counts = summary["friction_counts"]
    for key in FRICTION_KEYS:
        print(f"  {key}: {friction_counts.get(key, 0)}")

    print("\nper-site:")
    print("web_name | tasks | answer | handled | handling | friction")
    print("--- | ---: | ---: | ---: | --- | ---")
    for site, row in summary["per_site"]:
        tasks = row["tasks"]
        answer = row["answer_success"]
        handled = row["handled_success"]
        print(
            f"{site} | {tasks} | {answer}/{tasks} | {handled}/{tasks} | "
            f"{_format_counter(row['handling'])} | {_format_counter(row['friction'])}"
        )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    score_parser = subparsers.add_parser("score", help="score a completed WebVoyager JSONL run")
    score_parser.add_argument("--corpus", type=Path, required=True)
    score_parser.add_argument("--results", type=Path, required=True)

    validate_parser = subparsers.add_parser("validate", help="validate WebVoyager JSONL without scoring")
    validate_parser.add_argument("--corpus", type=Path, required=True)
    validate_parser.add_argument("--results", type=Path, required=True)

    args = parser.parse_args(argv)

    if args.command in {"score", "validate"}:
        try:
            corpus = load_jsonl(args.corpus)
            results = load_jsonl(args.results)
            if args.command == "score":
                print_score(score(corpus, results))
            else:
                validate(corpus, results)
                print(f"validation ok: {len(results)} results for {len(corpus)} corpus tasks")
        except ValidationIssue as exc:
            for warning in exc.warnings:
                print(f"warning: {warning}", file=sys.stderr)
            for error in exc.errors:
                print(f"error: {error}", file=sys.stderr)
            return 1
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

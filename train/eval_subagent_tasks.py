#!/usr/bin/env python3
"""Score subagent task runs with and without tool hints.

This script compares two completed run logs against a fixed task corpus.
It does not launch subagents itself; the caller supplies the recorded
results from the hinted run and the no-hint run.

Expected run result format (JSON array or JSONL):
  {
    "task_id": "...",
    "success": true,
    "answer": "...",
    "steps": 7,
    "elapsed_ms": 1234,
    "tool_hint_used": true
  }
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = REPO / "train" / "corpus" / "subagent_tasks.json"


def load_json_or_jsonl(path: Path) -> list[dict]:
    raw = path.read_text().strip()
    if not raw:
        return []
    if raw.startswith("["):
        return json.loads(raw)
    rows = []
    for line in raw.splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def normalize_answer(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def score(tasks: list[dict], results: list[dict]) -> dict:
    by_id = {r.get("task_id"): r for r in results if r.get("task_id")}
    rows = []
    for task in tasks:
        task_id = task.get("task_id") or task["url"]
        result = by_id.get(task_id, {})
        expected = normalize_answer(task.get("expected_answer"))
        answer = normalize_answer(result.get("answer"))
        match = task.get("match", "exact")
        ok = False
        if result.get("success") is True:
            if match == "contains":
                ok = expected.lower() in answer.lower()
            else:
                ok = answer == expected
        rows.append({
            "task_id": task_id,
            "url": task["url"],
            "expected": expected,
            "answer": answer,
            "success": bool(result.get("success")),
            "ok": ok,
            "steps": result.get("steps"),
            "elapsed_ms": result.get("elapsed_ms"),
            "tool_hint_used": result.get("tool_hint_used"),
        })

    completed = [r for r in rows if r["ok"]]
    success_rate = len(completed) / max(len(rows), 1)
    steps = [r["steps"] for r in rows if isinstance(r.get("steps"), (int, float))]
    elapsed = [r["elapsed_ms"] for r in rows if isinstance(r.get("elapsed_ms"), (int, float))]
    return {
        "success_rate": success_rate,
        "mean_steps": statistics.mean(steps) if steps else None,
        "mean_elapsed_ms": statistics.mean(elapsed) if elapsed else None,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--hinted-results", type=Path, required=True)
    parser.add_argument("--nohint-results", type=Path, required=True)
    args = parser.parse_args()

    tasks = json.loads(args.corpus.read_text())
    hinted = load_json_or_jsonl(args.hinted_results)
    nohint = load_json_or_jsonl(args.nohint_results)

    a = score(tasks, hinted)
    b = score(tasks, nohint)

    print(f"hinted success: {a['success_rate']:.3f}")
    print(f"nohint  success: {b['success_rate']:.3f}")
    print(json.dumps({"hinted": a, "nohint": b}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

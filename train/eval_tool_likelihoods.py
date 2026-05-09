#!/usr/bin/env python3
"""Small A/B eval harness for tool-likelihood ranking.

Compares two unbrowser binaries against a tiny fixed corpus and reports
top-1 tool recommendation accuracy for each side.

Usage:
  python3 train/eval_tool_likelihoods.py --binary-a ./target/release/unbrowser --binary-b ./target/alt/unbrowser
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = REPO / "train" / "corpus" / "tool_likelihoods_ab.json"


def load_cases(path: Path) -> list[dict]:
    return json.loads(path.read_text())


def _rpc_run(binary: Path, url: str) -> dict:
    proc = subprocess.run(
        [str(binary)],
        input=(
            '{"jsonrpc":"2.0","id":1,"method":"navigate","params":{"url":'
            + json.dumps(url)
            + '}}\n'
            '{"jsonrpc":"2.0","id":2,"method":"close"}\n'
        ).encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode(errors="replace") or f"{binary} exited {proc.returncode}")
    for line in proc.stdout.decode(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if payload.get("id") == 1:
            return payload.get("result") or {}
    raise RuntimeError(f"no navigate result returned by {binary}")


def validate_result_shape(result: dict, binary: Path) -> None:
    recs = result.get("tool_recommendations")
    probs = result.get("tool_likelihoods")
    if not isinstance(recs, list) or not isinstance(probs, dict):
        raise RuntimeError(
            f"{binary} does not emit tool ranking fields; "
            "build the matching release before running this eval"
        )


def top_tool(result: dict) -> str | None:
    recs = result.get("tool_recommendations") or []
    if isinstance(recs, list) and recs:
        first = recs[0]
        if isinstance(first, str):
            return first
    probs = result.get("tool_likelihoods") or {}
    if isinstance(probs, dict):
        best = None
        best_score = float("-inf")
        for name, score in probs.items():
            if name in {"confidence", "margin"}:
                continue
            try:
                val = float(score)
            except (TypeError, ValueError):
                continue
            if val > best_score:
                best = name
                best_score = val
        return best
    return None


def run(binary: Path, cases: list[dict]) -> dict:
    correct = 0
    rows = []
    for case in cases:
        result = _rpc_run(binary, case["url"])
        validate_result_shape(result, binary)
        predicted = top_tool(result)
        expected = case.get("expected_tool")
        ok = predicted == expected
        correct += int(ok)
        rows.append({
            "url": case["url"],
            "expected": expected,
            "predicted": predicted,
            "ok": ok,
        })
    return {"accuracy": correct / max(len(cases), 1), "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary-a", type=Path, required=True)
    parser.add_argument("--binary-b", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    args = parser.parse_args()

    cases = load_cases(args.corpus)
    a = run(args.binary_a, cases)
    b = run(args.binary_b, cases)

    print(f"A accuracy: {a['accuracy']:.3f}")
    print(f"B accuracy: {b['accuracy']:.3f}")
    print(json.dumps({"a": a, "b": b}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

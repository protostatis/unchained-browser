#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "train"))

import webvoyager_eval  # noqa: E402


def _result(task: dict, success: bool, handled_success: bool, handling: str, friction: Optional[dict] = None) -> dict:
    return {
        "task_id": task["task_id"],
        "run_timestamp": "2026-05-17T00:00:00Z",
        "web_name": task["web_name"],
        "start_url": task["start_url"],
        "question": task["question"],
        "success": success,
        "handled_success": handled_success,
        "handling": handling,
        "confidence": 0.9,
        "unbrowser_signals": {},
        "friction": friction or {},
    }


class WebVoyagerEvalTest(unittest.TestCase):
    def test_scores_arbitrary_jsonl_corpus(self):
        corpus = [
            {"task_id": "a", "web_name": "Site A", "start_url": "https://a.test/", "question": "A?"},
            {"task_id": "b", "web_name": "Site B", "start_url": "https://b.test/", "question": "B?"},
            {"task_id": "c", "web_name": "Site B", "start_url": "https://b.test/", "question": "C?"},
        ]
        results = [
            _result(corpus[0], True, True, "answered", {"eval_used": True}),
            _result(corpus[1], False, True, "browser_routed", {"browser_routed": True}),
            _result(corpus[2], False, False, "rate_limited", {"rate_limited": True}),
        ]

        summary = webvoyager_eval.score(corpus, results)

        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["answer_success"], 1)
        self.assertEqual(summary["handled_success"], 2)
        self.assertEqual(summary["handling_counts"]["answered"], 1)
        self.assertEqual(summary["handling_counts"]["browser_routed"], 1)
        self.assertEqual(summary["friction_counts"]["eval_used"], 1)
        self.assertEqual(summary["friction_counts"]["browser_routed"], 1)

    def test_validation_rejects_missing_and_duplicate_results(self):
        corpus = [
            {"task_id": "a", "web_name": "Site A", "start_url": "https://a.test/", "question": "A?"},
            {"task_id": "b", "web_name": "Site B", "start_url": "https://b.test/", "question": "B?"},
        ]
        results = [_result(corpus[0], True, True, "answered"), _result(corpus[0], True, True, "answered")]

        with self.assertRaises(webvoyager_eval.ValidationIssue) as ctx:
            webvoyager_eval.score(corpus, results)

        joined = "\n".join(ctx.exception.errors)
        self.assertIn("duplicate task_id: a", joined)
        self.assertIn("missing result for corpus task_id: b", joined)

    def test_validation_rejects_unknown_handling(self):
        corpus = [{"task_id": "a", "web_name": "Site A", "start_url": "https://a.test/", "question": "A?"}]
        results = [_result(corpus[0], False, False, "mystery")]

        with self.assertRaises(webvoyager_eval.ValidationIssue) as ctx:
            webvoyager_eval.score(corpus, results)

        self.assertIn("unknown handling", "\n".join(ctx.exception.errors))

    def test_cli_prints_core_metrics(self):
        corpus = [{"task_id": "a", "web_name": "Site A", "start_url": "https://a.test/", "question": "A?"}]
        results = [_result(corpus[0], True, True, "answered", {"noisy_text": True})]

        with tempfile.TemporaryDirectory(prefix="wv_eval_test_") as tmp:
            tmp_path = Path(tmp)
            corpus_path = tmp_path / "corpus.jsonl"
            results_path = tmp_path / "results.jsonl"
            corpus_path.write_text("\n".join(json.dumps(row) for row in corpus) + "\n")
            results_path.write_text("\n".join(json.dumps(row) for row in results) + "\n")

            proc = subprocess.run(
                [
                    sys.executable,
                    str(REPO / "train" / "webvoyager_eval.py"),
                    "score",
                    "--corpus",
                    str(corpus_path),
                    "--results",
                    str(results_path),
                ],
                check=False,
                text=True,
                capture_output=True,
            )

        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("answer success: 1/1 (100.0%)", proc.stdout)
        self.assertIn("handled success: 1/1 (100.0%)", proc.stdout)
        self.assertIn("noisy_text: 1", proc.stdout)


if __name__ == "__main__":
    unittest.main()

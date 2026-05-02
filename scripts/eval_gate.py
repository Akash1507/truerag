from __future__ import annotations

import os
import sys
import time

import requests


def _faithfulness_from_item(item: dict) -> float | None:
    scores = item.get("ragas_scores")
    if not isinstance(scores, dict):
        return None
    score = scores.get("faithfulness")
    if isinstance(score, int | float):
        return float(score)
    return None


def run() -> int:
    api_url = os.environ["TRUERAG_API_URL"].rstrip("/")
    agent_id = os.environ["EVAL_AGENT_ID"]
    api_key = os.environ["TRUERAG_API_KEY"]
    threshold_raw = os.environ.get("RAGAS_FAITHFULNESS_THRESHOLD")
    threshold = float(threshold_raw) if threshold_raw else 0.6
    timeout_minutes = int(os.environ.get("EVAL_TIMEOUT_MINUTES", "10"))
    poll_interval_seconds = int(os.environ.get("EVAL_POLL_INTERVAL_SECONDS", "30"))

    headers = {"X-API-Key": api_key}

    trigger = requests.post(f"{api_url}/v1/agents/{agent_id}/eval/run", headers=headers, timeout=60)
    trigger.raise_for_status()
    trigger_json = trigger.json()

    # Sync path returns score in-line.
    score = _faithfulness_from_item(trigger_json)
    if score is not None:
        print(f"RAGAS faithfulness: {score:.4f} (threshold: {threshold:.4f})")
        return 0 if score >= threshold else 1

    run_id = trigger_json.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        print("Eval gate failed: /eval/run response missing run_id")
        return 1

    deadline = time.time() + max(timeout_minutes, 0) * 60
    while time.time() < deadline:
        time.sleep(poll_interval_seconds)
        history = requests.get(
            f"{api_url}/v1/agents/{agent_id}/eval/history",
            headers=headers,
            params={"run_id": run_id, "limit": 100},
            timeout=60,
        )
        history.raise_for_status()
        history_json = history.json()

        items = history_json.get("items", [])
        if not isinstance(items, list):
            items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("run_id") != run_id:
                continue
            score = _faithfulness_from_item(item)
            if score is None:
                print(f"Eval gate failed: run {run_id} found without faithfulness score")
                return 1
            print(f"RAGAS faithfulness: {score:.4f} (threshold: {threshold:.4f})")
            return 0 if score >= threshold else 1

    print(f"Eval gate timed out after {timeout_minutes} minute(s) for run_id={run_id}")
    return 1


if __name__ == "__main__":
    sys.exit(run())

from __future__ import annotations

from collections.abc import Sequence
from unittest.mock import patch

from scripts import eval_gate


class _Resp:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _env() -> dict[str, str]:
    return {
        "TRUERAG_API_URL": "https://api.example.com",
        "EVAL_AGENT_ID": "agent-1",
        "TRUERAG_API_KEY": "k",
        "RAGAS_FAITHFULNESS_THRESHOLD": "0.6",
        "EVAL_TIMEOUT_MINUTES": "1",
        "EVAL_POLL_INTERVAL_SECONDS": "1",
    }


def test_sync_eval_passes_threshold() -> None:
    with patch("scripts.eval_gate.os.environ", _env()), patch(
        "scripts.eval_gate.requests.post",
        return_value=_Resp({"run_id": "run-1", "ragas_scores": {"faithfulness": 0.8}}),
    ), patch("scripts.eval_gate.requests.get"):
        assert eval_gate.run() == 0


def test_sync_eval_fails_threshold() -> None:
    with patch("scripts.eval_gate.os.environ", _env()), patch(
        "scripts.eval_gate.requests.post",
        return_value=_Resp({"run_id": "run-1", "ragas_scores": {"faithfulness": 0.2}}),
    ), patch("scripts.eval_gate.requests.get"):
        assert eval_gate.run() == 1


def test_async_eval_polls_history_and_passes() -> None:
    responses: Sequence[_Resp] = (
        _Resp({"run_id": "run-2", "status": "running"}, status_code=202),
    )
    history = [
        _Resp({"items": []}),
        _Resp({"items": [{"run_id": "run-2", "ragas_scores": {"faithfulness": 0.7}}]}),
    ]

    with patch("scripts.eval_gate.os.environ", _env()), patch(
        "scripts.eval_gate.requests.post", side_effect=responses
    ), patch("scripts.eval_gate.requests.get", side_effect=history), patch(
        "scripts.eval_gate.time.sleep"
    ):
        assert eval_gate.run() == 0


def test_async_eval_timeout_fails() -> None:
    env = _env()
    env["EVAL_TIMEOUT_MINUTES"] = "0"
    with patch("scripts.eval_gate.os.environ", env), patch(
        "scripts.eval_gate.requests.post",
        return_value=_Resp({"run_id": "run-2", "status": "running"}, status_code=202),
    ), patch("scripts.eval_gate.requests.get", return_value=_Resp({"items": []})), patch(
        "scripts.eval_gate.time.sleep"
    ):
        assert eval_gate.run() == 1


def test_async_eval_handles_history_shape_without_items() -> None:
    env = _env()
    env["EVAL_TIMEOUT_MINUTES"] = "0"
    with patch("scripts.eval_gate.os.environ", env), patch(
        "scripts.eval_gate.requests.post",
        return_value=_Resp({"run_id": "run-2", "status": "running"}, status_code=202),
    ), patch("scripts.eval_gate.requests.get", return_value=_Resp({"next_cursor": None})), patch(
        "scripts.eval_gate.time.sleep"
    ):
        assert eval_gate.run() == 1

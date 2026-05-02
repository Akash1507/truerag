from app.utils import cost_tracker


def test_init_cost_tracking_creates_accumulator() -> None:
    acc = cost_tracker.init_cost_tracking()
    assert acc.prompt_tokens == 0
    assert acc.completion_tokens == 0
    assert acc.embedding_calls == 0
    assert acc.reranker_calls == 0
    assert cost_tracker.get_cost_accumulator() is acc


def test_record_functions_increment_current_accumulator() -> None:
    acc = cost_tracker.init_cost_tracking()
    cost_tracker.record_llm_usage(10, 20)
    cost_tracker.record_embedding_call()
    cost_tracker.record_reranker_call()

    assert acc.prompt_tokens == 10
    assert acc.completion_tokens == 20
    assert acc.embedding_calls == 1
    assert acc.reranker_calls == 1


def test_record_functions_are_noops_without_accumulator() -> None:
    token = cost_tracker._cost_accumulator.set(None)
    try:
        cost_tracker.record_llm_usage(1, 2)
        cost_tracker.record_embedding_call()
        cost_tracker.record_reranker_call()
        assert cost_tracker.get_cost_accumulator() is None
    finally:
        cost_tracker._cost_accumulator.reset(token)

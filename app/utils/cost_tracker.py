from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class QueryCostAccumulator:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    embedding_calls: int = 0
    reranker_calls: int = 0


_cost_accumulator: ContextVar[QueryCostAccumulator | None] = ContextVar(
    "cost_accumulator",
    default=None,
)


def init_cost_tracking() -> QueryCostAccumulator:
    accumulator = QueryCostAccumulator()
    _cost_accumulator.set(accumulator)
    return accumulator


def get_cost_accumulator() -> QueryCostAccumulator | None:
    return _cost_accumulator.get()


def record_llm_usage(prompt_tokens: int, completion_tokens: int) -> None:
    accumulator = get_cost_accumulator()
    if accumulator is None:
        return
    accumulator.prompt_tokens += max(0, prompt_tokens)
    accumulator.completion_tokens += max(0, completion_tokens)


def record_embedding_call() -> None:
    accumulator = get_cost_accumulator()
    if accumulator is None:
        return
    accumulator.embedding_calls += 1


def record_reranker_call() -> None:
    accumulator = get_cost_accumulator()
    if accumulator is None:
        return
    accumulator.reranker_calls += 1

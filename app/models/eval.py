from datetime import UTC, datetime

from beanie import Document
from pydantic import BaseModel, Field


class EvalQuestion(BaseModel):
    question: str
    expected_answer: str


class EvalDataset(Document):
    agent_id: str
    tenant_id: str
    questions: list[EvalQuestion]
    created_at: datetime

    class Settings:
        name = "eval_datasets"


class RAGASScores(BaseModel):
    faithfulness: float
    answer_relevancy: float
    context_recall: float
    context_precision: float


class EvalExperiment(Document):
    agent_id: str
    tenant_id: str
    run_id: str
    config_snapshot: dict
    ragas_scores: RAGASScores
    baseline_delta: float
    triggered_alert: bool
    regression_reason: str | None = None
    created_at: datetime

    class Settings:
        name = "eval_experiments"


class EvalDatasetCreateRequest(BaseModel):
    questions: list[EvalQuestion] = Field(min_length=1)


class EvalDatasetCreateResponse(BaseModel):
    dataset_id: str
    agent_id: str
    tenant_id: str
    question_count: int
    created_at: datetime


class EvalRunResponse(BaseModel):
    run_id: str
    agent_id: str
    tenant_id: str
    ragas_scores: RAGASScores
    baseline_delta: float
    triggered_alert: bool
    regression_reason: str | None = None
    created_at: datetime


class EvalRunAcceptedResponse(BaseModel):
    run_id: str
    agent_id: str
    status: str = "running"


class EvalExperimentSummary(BaseModel):
    run_id: str
    ragas_scores: RAGASScores
    config_snapshot: dict
    baseline_delta: float
    triggered_alert: bool
    regression_reason: str | None = None
    created_at: datetime


class EvalHistoryResponse(BaseModel):
    items: list[EvalExperimentSummary]
    next_cursor: str | None

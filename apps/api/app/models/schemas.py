from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field


class UserOut(BaseModel):
    id: str
    email: EmailStr
    name: str
    created_at: datetime


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=80)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class RefreshIn(BaseModel):
    refresh_token: str


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class WorkspaceOut(BaseModel):
    id: str
    name: str
    description: str
    owner_id: str
    document_count: int = 0
    dataset_count: int = 0
    investigation_count: int = 0
    created_at: datetime


class Citation(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str
    source_type: str
    page: int | None = None
    section: str | None = None
    snippet: str
    score: float
    media_url: str | None = None


class ChartSpec(BaseModel):
    chart_type: Literal["bar", "line", "pie", "area", "scatter"] = "bar"
    title: str
    x_label: str = ""
    y_label: str = ""
    labels: list[str] = []
    series: list[dict[str, Any]] = []
    caption: str = ""


class EvidencePiece(BaseModel):
    kind: Literal["document", "dataset", "vision", "audio", "data"]
    source_name: str
    summary: str
    citation: Citation | None = None
    chart: ChartSpec | None = None


class ModelRunInfo(BaseModel):
    provider: str
    model: str
    task: str
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    fallback_used: bool = False


class InvestigationOut(BaseModel):
    id: str
    workspace_id: str
    conversation_id: str
    question: str
    answer: str
    capabilities: list[str] = []
    citations: list[Citation] = []
    charts: list[ChartSpec] = []
    evidence: list[EvidencePiece] = []
    confidence: float | None = None
    model_runs: list[ModelRunInfo] = []
    tool_calls: int = 0
    latency_ms: float = 0
    created_at: datetime


class DocumentOut(BaseModel):
    id: str
    workspace_id: str
    filename: str
    source_type: str
    content_type: str
    status: Literal["processing", "ready", "failed"]
    error: str | None = None
    num_chunks: int = 0
    num_pages: int = 0
    media_url: str | None = None
    size_bytes: int = 0
    created_at: datetime


class ColumnInfo(BaseModel):
    name: str
    dtype: str
    non_null: int
    unique: int


class DatasetOut(BaseModel):
    id: str
    workspace_id: str
    filename: str
    status: Literal["processing", "ready", "failed"]
    error: str | None = None
    num_rows: int = 0
    num_columns: int = 0
    columns: list[ColumnInfo] = []
    sample_rows: list[dict[str, Any]] = []
    size_bytes: int = 0
    created_at: datetime


class MediaAssetOut(BaseModel):
    id: str
    workspace_id: str
    kind: Literal["image", "audio", "file"]
    filename: str
    url: str
    transcript: str | None = None
    analysis: dict[str, Any] | None = None
    size_bytes: int = 0
    created_at: datetime


class ChatRequest(BaseModel):
    workspace_id: str
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None
    attachment_ids: list[str] = []
    audio_media_id: str | None = None


class ConversationOut(BaseModel):
    id: str
    workspace_id: str
    title: str
    updated_at: datetime


class EvalCaseOut(BaseModel):
    id: str
    question: str
    expected_answer: str
    expected_chunk_ids: list[str] = []
    category: str = "general"


class EvalRunSummary(BaseModel):
    id: str
    config: dict[str, Any]
    status: Literal["running", "completed", "failed"]
    num_cases: int
    retrieval_recall_at_5: float | None = None
    retrieval_mrr: float | None = None
    answer_correctness: float | None = None
    faithfulness: float | None = None
    citation_accuracy: float | None = None
    avg_latency_ms: float | None = None
    total_tokens: int = 0
    created_at: datetime


class EvalRunDetail(EvalRunSummary):
    results: list[dict[str, Any]] = []


class EvalConfig(BaseModel):
    workspace_id: str
    case_ids: list[str] = []
    categories: list[str] = []
    retrieval_mode: Literal["vector", "hybrid", "hybrid_rerank"] = "hybrid_rerank"
    max_cases: int = 20


class ObservabilitySummary(BaseModel):
    total_investigations: int = 0
    avg_latency_ms: float = 0
    p50_latency_ms: float = 0
    p95_latency_ms: float = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0
    fallback_rate: float = 0
    error_rate: float = 0
    provider_usage: list[dict[str, Any]] = []
    tool_usage: list[dict[str, Any]] = []

from typing import Any, TypedDict


class InvestigationState(TypedDict, total=False):
    workspace_id: str
    user_id: str
    conversation_id: str
    investigation_id: str
    question: str
    original_question: str
    history: list[dict]
    attachment_ids: list[str]
    audio_media_id: str | None
    capabilities: list[str]
    intent: str
    rewritten_query: str
    retrieval_mode: str
    document_filter: list[str]
    retrieved_chunks: list[dict]
    data_results: list[dict]
    vision_results: list[dict]
    audio_transcript: str | None
    evidence: list[dict]
    verification: dict
    retry_count: int
    answer: str
    citations: list[dict]
    charts: list[dict]
    confidence: float | None
    errors: list[str]
    workspace_sources: list[dict]
    total_steps: int

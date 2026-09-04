from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_current_user, require_workspace
from app.evaluation import runner
from app.models.schemas import EvalCaseOut, EvalConfig, EvalRunDetail, EvalRunSummary

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


def to_summary(run: dict) -> EvalRunSummary:
    return EvalRunSummary(
        id=run["_id"],
        config=run.get("config", {}),
        status=run["status"],
        error=run.get("error"),
        num_cases=run.get("num_cases", 0),
        retrieval_recall_at_5=run.get("retrieval_recall_at_5"),
        retrieval_mrr=run.get("retrieval_mrr"),
        answer_correctness=run.get("answer_correctness"),
        faithfulness=run.get("faithfulness"),
        citation_accuracy=run.get("citation_accuracy"),
        avg_latency_ms=run.get("avg_latency_ms"),
        created_at=run["created_at"],
    )


@router.get("/cases", response_model=list[EvalCaseOut])
async def list_cases(limit: int = 200, user: dict = Depends(get_current_user)) -> list[EvalCaseOut]:
    cases = await runner.list_cases(limit)
    return [
        EvalCaseOut(
            id=c["_id"],
            question=c["question"],
            expected_answer=c.get("expected_answer", ""),
            expected_chunk_ids=c.get("expected_chunk_ids", []),
            category=c.get("category", "general"),
        )
        for c in cases
    ]


class CaseIn(BaseModel):
    question: str
    expected_answer: str = ""
    expected_document_names: list[str] = []
    expected_chunk_ids: list[str] = []
    category: str = "general"


@router.post("/cases", status_code=201)
async def add_case(payload: CaseIn, user: dict = Depends(get_current_user)) -> dict:
    inserted = await runner.seed_cases([payload.model_dump()])
    if not inserted:
        raise HTTPException(status_code=400, detail="case already exists")
    return {"ok": True}


class SeedFromHistoryIn(BaseModel):
    workspace_id: str
    limit: int = 10


@router.post("/seed-from-history")
async def seed_from_history(payload: SeedFromHistoryIn, user: dict = Depends(get_current_user)) -> dict:
    await require_workspace(payload.workspace_id, user)
    inserted = await runner.seed_from_investigations(payload.workspace_id, payload.limit)
    if not inserted:
        raise HTTPException(
            status_code=400,
            detail="no past investigations to seed from (or all already seeded)",
        )
    return {"ok": True, "inserted": inserted}


@router.post("/run", response_model=EvalRunSummary, status_code=201)
async def run_evaluation(payload: EvalConfig, user: dict = Depends(get_current_user)) -> EvalRunSummary:
    await require_workspace(payload.workspace_id, user)
    run = await runner.create_and_run(
        workspace_id=payload.workspace_id,
        retrieval_mode=payload.retrieval_mode,
        case_ids=payload.case_ids,
        categories=payload.categories,
        max_cases=payload.max_cases,
    )
    return to_summary(run)


@router.get("/runs", response_model=list[EvalRunSummary])
async def list_runs(
    workspace_id: str = Query(..., description="Workspace ID (required)"),
    limit: int = Query(20, le=100),
    user: dict = Depends(get_current_user),
) -> list[EvalRunSummary]:
    await require_workspace(workspace_id, user)
    runs = await runner.list_runs(workspace_id, limit)
    return [to_summary(r) for r in runs]


@router.get("/runs/{run_id}", response_model=EvalRunDetail)
async def get_run(
    run_id: str, workspace_id: str = Query(..., description="Workspace ID (required)"),
    user: dict = Depends(get_current_user)
) -> EvalRunDetail:
    await require_workspace(workspace_id, user)
    run = await runner.get_run(run_id, workspace_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    summary = to_summary(run)
    return EvalRunDetail(**summary.model_dump(), results=run.get("results", []))

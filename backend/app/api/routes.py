from fastapi import APIRouter, Depends, Request

from app.agent.runtime import get_agent
from app.api.events import log_search
from app.api.quota import quota_limit
from app.api.security import client_ip, rate_limit, require_api_key
from app.schemas import AnalyzeRequest, AnalyzeResponse

router = APIRouter(prefix="/api", tags=["analysis"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    # Order = cheapest/most-protective first: auth, then in-memory burst guard, then
    # the Firestore-backed per-IP quota.
    dependencies=[Depends(require_api_key), Depends(rate_limit), Depends(quota_limit)],
)
async def analyze(
    req: AnalyzeRequest,
    request: Request,
    agent=Depends(get_agent),
) -> AnalyzeResponse:
    log_search(req.question, req.detector, client_ip(request))
    result = await agent.ainvoke({"question": req.question, "detector": req.detector})
    return AnalyzeResponse(
        question=req.question,
        briefing=result.get("briefing", ""),
        focus=result.get("focus"),
        sql=result.get("sql"),
        detection=result.get("detection"),
        root_cause=result.get("root_cause"),
        error=result.get("error"),
    )

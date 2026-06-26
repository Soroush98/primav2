from fastapi import APIRouter, Depends

from app.agent.runtime import get_agent
from app.api.security import rate_limit, require_api_key
from app.schemas import AnalyzeRequest, AnalyzeResponse

router = APIRouter(prefix="/api", tags=["analysis"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    dependencies=[Depends(require_api_key), Depends(rate_limit)],
)
async def analyze(
    req: AnalyzeRequest,
    agent=Depends(get_agent),
) -> AnalyzeResponse:
    result = await agent.ainvoke({"question": req.question})
    return AnalyzeResponse(
        question=req.question,
        briefing=result.get("briefing", ""),
        focus=result.get("focus"),
        sql=result.get("sql"),
        detection=result.get("detection"),
        root_cause=result.get("root_cause"),
        error=result.get("error"),
    )

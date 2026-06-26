from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class AnalyzeResponse(BaseModel):
    question: str
    briefing: str
    focus: dict | None = None      # parsed intent (orchestrator)
    sql: str | None = None         # the read-only query the agent ran
    detection: dict | None = None
    root_cause: dict | None = None
    error: str | None = None

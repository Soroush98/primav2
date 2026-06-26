from typing import Literal

from pydantic import BaseModel, Field

# auto = data shape decides; baseline = force MAD/EVT; omnianomaly / forecast force
# the deep-learning / Chronos-Bolt arms (both steer the SQL to a per-machine series).
DetectorMode = Literal["auto", "baseline", "omnianomaly", "forecast"]


class AnalyzeRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    detector: DetectorMode = "auto"


class AnalyzeResponse(BaseModel):
    question: str
    briefing: str
    focus: dict | None = None      # parsed intent (orchestrator)
    sql: str | None = None         # the read-only query the agent ran
    detection: dict | None = None
    root_cause: dict | None = None
    error: str | None = None

# primav2 — backend

FastAPI service: agent API + detectors + eval. Gemini reasoning runs on Vertex AI.

## Run

```bash
uv sync
cp .env.example .env                 # set GOOGLE_CLOUD_PROJECT
gcloud auth application-default login # ADC for Vertex AI
uv run fastapi dev app/main.py       # http://localhost:8000  (docs at /docs)
```

## Test

```bash
uv run pytest          # network-free; LLM is faked via dependency_overrides
```

## Layout

```
app/
  main.py        app factory + lifespan + CORS
  config.py      pydantic-settings (env once, cached)
  schemas.py     request/response models
  api/routes.py  /api/health, /api/analyze
  llm/gemini.py  Gemini-on-Vertex provider (get_llm DI seam)
```

## Next

- `agent/`      LangGraph fleet (orchestrator → sql_analyst → detector → root_cause → narrator)
- `detectors/`  MAD/EVT baseline + OmniAnomaly arm
- `eval/`       raw-F1 + point-adjusted-F1 harness (build first)

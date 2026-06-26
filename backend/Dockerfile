# primav2 backend — FastAPI on Cloud Run.
# Lean image: production deps only (no dev group, no `ml`/torch — the API ships the
# MAD/EVT baseline; OmniAnomaly is an offline arm). Auth is ADC from the attached
# Cloud Run service account; no keys are baked in.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PORT=8080

# Dependency layer (cached until pyproject/lock change).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# OmniAnomaly serving arm: GCS (checkpoint download) + CPU-only torch (no CUDA, so
# ~200 MB not ~2 GB). Kept out of pyproject so local/dev installs stay lean; the app
# imports both lazily and degrades to the baseline if they are absent.
RUN uv pip install --no-cache google-cloud-storage \
 && uv pip install --no-cache --index-url https://download.pytorch.org/whl/cpu torch

# Chronos-Bolt forecaster arm: install + BAKE the tiny model into the image so cold
# starts never hit the HuggingFace Hub. transformers is heavy — this grows the image;
# the arm is opt-in via CHRONOS_MODEL (unset ⇒ "forecast" mode falls back to baseline).
ENV HF_HOME=/app/hf_cache
RUN uv pip install --no-cache chronos-forecasting \
 && uv run --no-sync python -c "from chronos import BaseChronosPipeline; BaseChronosPipeline.from_pretrained('amazon/chronos-bolt-tiny')"

# App source.
COPY app ./app

EXPOSE 8080
# Bind to Cloud Run's injected $PORT; one process per container (Cloud Run scales out).
CMD uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process configuration, read once from the environment / `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Vertex AI / Gemini
    google_cloud_project: str = ""
    google_cloud_location: str = "global"
    gemini_model: str = "gemini-2.5-flash"

    # BigQuery
    bigquery_dataset: str = "alibaba_cluster"
    bigquery_max_bytes_billed: int = 50_000_000_000  # ~50 GB cost cap per query
    bigquery_max_rows: int = 50_000  # cap rows materialized client-side (bounds memory)

    # OmniAnomaly serving — gs:// or local path to the trained checkpoint. Empty =
    # disabled (the agent serves the MAD/EVT baseline only). Loaded once at startup.
    omni_checkpoint_uri: str = ""

    # Chronos-Bolt forecaster arm — HF model id (e.g. "amazon/chronos-bolt-tiny").
    # Empty = disabled; the "forecast" mode then falls back to the baseline.
    chronos_model: str = ""

    # CORS
    frontend_origin: str = "http://localhost:3000"

    # API protection. Auth is enforced only when api_key is set (prod); empty = open (local dev).
    api_key: str = ""
    rate_limit_per_min: int = 30  # per client IP, per instance; 0 disables

    # Per-IP search quota, backed by Firestore — distributed + persistent across
    # instances, unlike rate_limit_per_min (in-memory/best-effort). 0 disables (the
    # default, so local dev and tests never touch Firestore). In prod set
    # quota_per_window=10 to block an IP after 10 searches until the window elapses.
    quota_per_window: int = 0
    quota_window_sec: int = 86_400  # rolling window length; default 1 day


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor — the DI seam tests can override."""
    return Settings()

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

    # CORS
    frontend_origin: str = "http://localhost:3000"

    # API protection. Auth is enforced only when api_key is set (prod); empty = open (local dev).
    api_key: str = ""
    rate_limit_per_min: int = 30  # per client IP, per instance; 0 disables


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor — the DI seam tests can override."""
    return Settings()

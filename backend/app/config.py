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

    # CORS
    frontend_origin: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor — the DI seam tests can override."""
    return Settings()

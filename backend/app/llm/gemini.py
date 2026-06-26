"""Gemini-on-Vertex provider.

Uses the unified `google-genai` SDK pointed at Vertex AI. Authentication is GCP
Application Default Credentials (`gcloud auth application-default login`) — there
is no API key in this path.

Exposed through `get_llm()` so routes depend on the interface and tests can swap a
fake via `app.dependency_overrides`.
"""

from functools import lru_cache

from fastapi import Depends
from google import genai
from google.genai import types

from app.config import Settings, get_settings


class GeminiProvider:
    def __init__(self, settings: Settings) -> None:
        self._client = genai.Client(
            vertexai=True,
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
        )
        self._model = settings.gemini_model

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
        )
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config=config,
        )
        return response.text or ""


@lru_cache
def _provider() -> GeminiProvider:
    # One client per process; the underlying genai.Client is reused across requests.
    return GeminiProvider(get_settings())


def get_llm(
    _settings: Settings = Depends(get_settings),
) -> GeminiProvider:
    return _provider()

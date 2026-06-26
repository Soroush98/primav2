"""Network-free API tests: the agent graph is swapped for a fake via the DI seam."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.runtime import get_agent
from app.config import Settings, get_settings
from app.main import app


class FakeAgent:
    async def ainvoke(self, state: dict) -> dict:
        return {
            "briefing": f"stub briefing for: {state['question']}",
            "detection": {"n": 0},
        }


@pytest.fixture
def client():
    app.dependency_overrides[get_agent] = lambda: FakeAgent()
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


async def test_health(client):
    async with client as c:
        r = await c.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_analyze(client):
    async with client as c:
        r = await c.post("/api/analyze", json={"question": "any anomalies today?"})
    assert r.status_code == 200
    body = r.json()
    assert body["question"] == "any anomalies today?"
    assert "stub briefing" in body["briefing"]


async def test_analyze_requires_api_key_when_configured():
    app.dependency_overrides[get_agent] = lambda: FakeAgent()
    app.dependency_overrides[get_settings] = lambda: Settings(api_key="s3cret")
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            missing = await c.post("/api/analyze", json={"question": "x"})
            valid = await c.post(
                "/api/analyze", json={"question": "x"}, headers={"X-API-Key": "s3cret"}
            )
    finally:
        app.dependency_overrides.clear()
    assert missing.status_code == 401
    assert valid.status_code == 200

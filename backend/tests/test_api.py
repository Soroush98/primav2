"""Network-free API tests: the agent graph is swapped for a fake via the DI seam."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.runtime import get_agent
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
        r = await c.post("/api/analyze", json={"question": "any DDoS spikes today?"})
    assert r.status_code == 200
    body = r.json()
    assert body["question"] == "any DDoS spikes today?"
    assert "stub briefing" in body["briefing"]

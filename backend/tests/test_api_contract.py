"""Contract + negative-path tests for the public API surface (docs/test-cases/TC-API.md).

Techniques: equivalence partitioning + boundary-value analysis on AnalyzeRequest,
error-body shape assertions on every rejection path, and an OpenAPI contract
snapshot so a breaking schema change fails here before a consumer sees it.
Network-free: the agent is faked via the DI seam, like test_api.py.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.runtime import get_agent
from app.api import security
from app.config import Settings, get_settings
from app.main import app


class FakeAgent:
    async def ainvoke(self, state: dict) -> dict:
        return {"briefing": "stub briefing", "detection": {"n": 0}}


@pytest.fixture(autouse=True)
def _isolate():
    """Each test gets a clean rate-limiter and DI table — the in-memory sliding
    window is module-global, so without this, tests would share IP buckets."""
    security._HITS.clear()
    app.dependency_overrides[get_agent] = lambda: FakeAgent()
    yield
    app.dependency_overrides.clear()
    security._HITS.clear()


def _client(settings: Settings | None = None) -> AsyncClient:
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# --------------------------------------------------- input boundaries (BVA / EP)


async def test_question_at_max_length_accepted():
    """TC-API-01: boundary — exactly max_length (2000) is valid."""
    async with _client() as c:
        r = await c.post("/api/analyze", json={"question": "q" * 2000})
    assert r.status_code == 200


async def test_question_over_max_length_rejected():
    """TC-API-02: boundary — max_length+1 (2001) is a 422, not a truncation."""
    async with _client() as c:
        r = await c.post("/api/analyze", json={"question": "q" * 2001})
    assert r.status_code == 422
    assert r.json()["detail"]  # pydantic explains which field failed


async def test_question_empty_rejected():
    """TC-API-03: boundary — min_length-1 (empty string) is a 422."""
    async with _client() as c:
        r = await c.post("/api/analyze", json={"question": ""})
    assert r.status_code == 422


async def test_question_missing_rejected():
    """TC-API-04: EP — required field absent."""
    async with _client() as c:
        r = await c.post("/api/analyze", json={})
    assert r.status_code == 422


async def test_non_json_body_rejected():
    """TC-API-05: EP — wrong content type / unparseable body."""
    async with _client() as c:
        r = await c.post("/api/analyze", content=b"not json", headers={"Content-Type": "text/plain"})
    assert r.status_code == 422


@pytest.mark.parametrize("mode", ["auto", "baseline", "omnianomaly", "forecast"])
async def test_every_documented_detector_mode_accepted(mode):
    """TC-API-06: EP — each member of the DetectorMode enum is a valid partition."""
    async with _client() as c:
        r = await c.post("/api/analyze", json={"question": "x", "detector": mode})
    assert r.status_code == 200


async def test_unknown_detector_mode_rejected():
    """TC-API-07: EP — a value outside the enum is rejected, not coerced."""
    async with _client() as c:
        r = await c.post("/api/analyze", json={"question": "x", "detector": "quantum"})
    assert r.status_code == 422


# ------------------------------------------------------------- auth error shape


async def test_wrong_api_key_401_with_stable_error_shape():
    """TC-API-08: wrong key → 401 with the documented {code, message} body, and the
    submitted key value is never echoed back."""
    async with _client(Settings(api_key="s3cret")) as c:
        r = await c.post(
            "/api/analyze", json={"question": "x"}, headers={"X-API-Key": "wrong-key-123"}
        )
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "unauthorized"
    assert "wrong-key-123" not in r.text


async def test_health_requires_no_auth():
    """TC-API-09: /api/health stays open even when an API key is enforced (it is
    the Cloud Run liveness / k6 target and must never 401)."""
    async with _client(Settings(api_key="s3cret")) as c:
        r = await c.get("/api/health")
    assert r.status_code == 200


# ------------------------------------------------------------------- rate limit


async def test_rate_limit_429_after_burst_with_stable_shape():
    """TC-API-10: requests over rate_limit_per_min from one IP → 429 {code:rate_limited}."""
    settings = Settings(rate_limit_per_min=2)
    headers = {"X-Real-Client-IP": "203.0.113.10"}
    async with _client(settings) as c:
        first = await c.post("/api/analyze", json={"question": "x"}, headers=headers)
        second = await c.post("/api/analyze", json={"question": "x"}, headers=headers)
        third = await c.post("/api/analyze", json={"question": "x"}, headers=headers)
    assert (first.status_code, second.status_code) == (200, 200)
    assert third.status_code == 429
    assert third.json()["detail"]["code"] == "rate_limited"


async def test_rate_limit_buckets_are_per_ip():
    """TC-API-11: the window is per client IP — one saturated IP must not block another."""
    settings = Settings(rate_limit_per_min=1)
    async with _client(settings) as c:
        a1 = await c.post("/api/analyze", json={"question": "x"}, headers={"X-Real-Client-IP": "203.0.113.11"})
        a2 = await c.post("/api/analyze", json={"question": "x"}, headers={"X-Real-Client-IP": "203.0.113.11"})
        b1 = await c.post("/api/analyze", json={"question": "x"}, headers={"X-Real-Client-IP": "203.0.113.12"})
    assert a1.status_code == 200
    assert a2.status_code == 429
    assert b1.status_code == 200


# --------------------------------------------------------------- OpenAPI contract


async def test_openapi_contract_pins_the_public_schema():
    """TC-API-12: contract snapshot. The frontend proxy, the e2e stub backend and the
    k6 scripts all depend on this shape — a breaking change must fail here first."""
    async with _client() as c:
        spec = (await c.get("/openapi.json")).json()

    assert "post" in spec["paths"]["/api/analyze"]
    assert "get" in spec["paths"]["/api/health"]

    schemas = spec["components"]["schemas"]
    request = schemas["AnalyzeRequest"]["properties"]
    assert request["question"]["minLength"] == 1
    assert request["question"]["maxLength"] == 2000
    assert set(request["detector"]["enum"]) == {"auto", "baseline", "omnianomaly", "forecast"}

    response = schemas["AnalyzeResponse"]
    assert set(response["required"]) >= {"question", "briefing"}
    for field in ("focus", "sql", "detection", "root_cause", "error"):
        assert field in response["properties"], f"response contract lost field {field!r}"

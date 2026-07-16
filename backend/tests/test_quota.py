"""Quota tests (docs/test-cases/TC-API.md, cases 13-15): the pure window-counter
decision, its window boundaries (BVA), and the full quota_limit dependency driven
through the HTTP surface against a fake Firestore — including the degrade-open
failure mode (a storage outage must never take the API down)."""

import pytest
from httpx import ASGITransport, AsyncClient

import app.api.quota as quota
from app.agent.runtime import get_agent
from app.config import Settings, get_settings
from app.main import app
from app.api.quota import _decide, _safe_id


def test_allows_up_to_limit_then_blocks():
    state: dict = {}
    now = 1000.0
    for expected_count in (1, 2, 3):
        allowed, state = _decide(state, now, limit=3, window=60)
        assert allowed
        assert state["count"] == expected_count
    # 4th hit inside the same window is blocked, and the count is not bumped.
    allowed, state = _decide(state, now, limit=3, window=60)
    assert not allowed
    assert state["count"] == 3


def test_window_resets_after_elapsed():
    # 5 hits already used, but the window (60s) has fully elapsed by now=100.
    allowed, state = _decide({"window_start": 0.0, "count": 5}, now=100.0, limit=3, window=60)
    assert allowed
    assert state["count"] == 1
    assert state["window_start"] == 100.0


def test_blocked_request_does_not_advance_window():
    blocked = {"window_start": 1000.0, "count": 3}
    allowed, state = _decide(blocked, now=1030.0, limit=3, window=60)
    assert not allowed
    assert state == blocked


# -------------------------------------------------- window boundaries (TC-API-13)


def test_window_boundary_exactly_elapsed_resets():
    """BVA: elapsed == window is the reset edge (`>=` in _decide, not `>`)."""
    allowed, state = _decide({"window_start": 0.0, "count": 3}, now=60.0, limit=3, window=60)
    assert allowed
    assert state == {"window_start": 60.0, "count": 1}


def test_window_boundary_one_tick_before_still_blocked():
    """BVA: elapsed == window - ε must still be inside the old window."""
    allowed, state = _decide({"window_start": 0.0, "count": 3}, now=59.999, limit=3, window=60)
    assert not allowed
    assert state["count"] == 3


def test_count_never_exceeds_limit_or_goes_negative():
    state: dict = {}
    for _ in range(10):
        _, state = _decide(state, now=5.0, limit=3, window=60)
        assert 0 <= state["count"] <= 3


def test_safe_id_never_yields_invalid_firestore_ids():
    assert _safe_id("2001:db8::1") == "2001:db8::1"
    assert _safe_id("bad/slash/ip") == "bad_slash_ip"
    assert _safe_id("") == "unknown"


# --------------------------- quota_limit through the API, fake Firestore (TC-API-14)


class _FakeSnap:
    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return dict(self._data) if self._data else None


class _FakeRef:
    def __init__(self, store, key):
        self.store, self.key = store, key

    def get(self, transaction=None):
        return _FakeSnap(self.store.get(self.key))


class _FakeTxn:
    def set(self, ref, state):
        ref.store[ref.key] = state


class _FakeDb:
    """Duck-typed Firestore: collection().document() → ref, transaction() → txn."""

    def __init__(self):
        self.store: dict[str, dict] = {}

    def collection(self, name):
        assert name == "ip_quota"
        return self

    def document(self, key):
        return _FakeRef(self.store, key)

    def transaction(self):
        return _FakeTxn()


class _FakeAgent:
    async def ainvoke(self, state: dict) -> dict:
        return {"briefing": "stub", "detection": {"n": 0}}


@pytest.fixture
def quota_client(monkeypatch):
    """API client with quota_per_window=2 backed by the fake store. The real
    @firestore.transactional decorator needs a live Transaction, so it is swapped
    for identity — the retry semantics are Google's to test; the decision is ours."""
    import google.cloud.firestore as firestore_mod

    fake = _FakeDb()
    monkeypatch.setattr(quota, "_get_db", lambda project: fake)
    monkeypatch.setattr(firestore_mod, "transactional", lambda fn: fn)
    app.dependency_overrides[get_agent] = lambda: _FakeAgent()
    app.dependency_overrides[get_settings] = lambda: Settings(
        quota_per_window=2, quota_window_sec=3600
    )
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test"), fake
    app.dependency_overrides.clear()


async def test_quota_blocks_with_429_after_limit(quota_client):
    client, fake = quota_client
    headers = {"X-Real-Client-IP": "198.51.100.7"}
    async with client as c:
        r1 = await c.post("/api/analyze", json={"question": "x"}, headers=headers)
        r2 = await c.post("/api/analyze", json={"question": "x"}, headers=headers)
        r3 = await c.post("/api/analyze", json={"question": "x"}, headers=headers)
    assert (r1.status_code, r2.status_code) == (200, 200)
    assert r3.status_code == 429
    assert r3.json()["detail"]["code"] == "quota_exceeded"
    assert fake.store["198.51.100.7"]["count"] == 2  # blocked hit did not increment


async def test_quota_is_tracked_per_ip(quota_client):
    client, fake = quota_client
    async with client as c:
        for ip in ("198.51.100.8", "198.51.100.9"):
            r = await c.post(
                "/api/analyze", json={"question": "x"}, headers={"X-Real-Client-IP": ip}
            )
            assert r.status_code == 200
    assert set(fake.store) == {"198.51.100.8", "198.51.100.9"}


async def test_quota_degrades_open_when_store_errors(monkeypatch):
    """TC-API-15: a Firestore outage must not become an API outage."""

    class _ExplodingDb(_FakeDb):
        def transaction(self):
            raise RuntimeError("firestore is down")

    import google.cloud.firestore as firestore_mod

    monkeypatch.setattr(quota, "_get_db", lambda project: _ExplodingDb())
    monkeypatch.setattr(firestore_mod, "transactional", lambda fn: fn)
    app.dependency_overrides[get_agent] = lambda: _FakeAgent()
    app.dependency_overrides[get_settings] = lambda: Settings(
        quota_per_window=1, quota_window_sec=3600
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r1 = await c.post("/api/analyze", json={"question": "x"})
            r2 = await c.post("/api/analyze", json={"question": "x"})
    finally:
        app.dependency_overrides.clear()
    assert r1.status_code == 200
    assert r2.status_code == 200  # over the limit, but the check degraded open


async def test_quota_disabled_never_touches_firestore(monkeypatch):
    """quota_per_window=0 (the default) must short-circuit before any client init."""

    def _boom(project):
        raise AssertionError("Firestore client must not be constructed when quota is off")

    monkeypatch.setattr(quota, "_get_db", _boom)
    app.dependency_overrides[get_agent] = lambda: _FakeAgent()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/analyze", json={"question": "x"})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200

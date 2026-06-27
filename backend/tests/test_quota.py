"""Unit tests for the pure window-counter decision (no Firestore needed)."""

from app.api.quota import _decide


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

"""Per-IP search quota backed by Firestore — a distributed, persistent counter that
every Cloud Run instance shares, unlike the in-memory burst limiter in security.py.

It enforces "N searches per rolling window, then 429 until the window resets". The
window self-heals, so a shared/CGNAT IP is never locked out forever (and you can clear
a ban early by deleting its doc: `gcloud firestore documents delete ip_quota/<ip>`).

Disabled when `quota_per_window <= 0` (the default), so local dev and tests never touch
Firestore. If Firestore is unreachable the check degrades *open* (logs a warning) so a
storage hiccup can't take the whole API down.

This is a sync `def` dependency on purpose: FastAPI runs it in a threadpool, so the
blocking Firestore client never stalls the event loop.
"""

from __future__ import annotations

import logging
import time

from fastapi import Depends, HTTPException, Request

from app.api.security import client_ip
from app.config import Settings, get_settings

log = logging.getLogger(__name__)

_COLLECTION = "ip_quota"
_db = None
_init_failed = False


def _get_db(project: str):
    """Lazily build a cached Firestore client. Returns None (once) if init fails so we
    don't retry a broken client on every request."""
    global _db, _init_failed
    if _db is not None or _init_failed:
        return _db
    try:
        from google.cloud import firestore

        _db = firestore.Client(project=project or None)
    except Exception:  # noqa: BLE001 — never take the API down on a storage init failure
        _init_failed = True
        log.warning("Firestore unavailable; per-IP quota disabled", exc_info=True)
    return _db


def _decide(data: dict, now: float, limit: int, window: float) -> tuple[bool, dict]:
    """Pure fixed-window-counter decision: (allowed, new_state). Resets the count once
    the window has elapsed. Side-effect-free so the windowing logic is unit-testable
    without Firestore (see tests/test_quota.py)."""
    window_start = data.get("window_start", now)
    count = data.get("count", 0)
    if now - window_start >= window:
        window_start, count = now, 0
    if count >= limit:
        return False, {"window_start": window_start, "count": count}
    return True, {"window_start": window_start, "count": count + 1}


def _safe_id(ip: str) -> str:
    # Firestore document ids may not contain '/'. IPv4/IPv6 are otherwise safe.
    return ip.replace("/", "_") or "unknown"


def quota_limit(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    limit = settings.quota_per_window
    if limit <= 0:  # disabled (local dev / tests)
        return
    db = _get_db(settings.google_cloud_project)
    if db is None:  # Firestore unavailable → degrade open
        return

    from google.cloud import firestore

    ref = db.collection(_COLLECTION).document(_safe_id(client_ip(request)))
    now = time.time()
    window = float(settings.quota_window_sec)

    @firestore.transactional
    def _run(txn) -> bool:
        snap = ref.get(transaction=txn)
        allowed, new_state = _decide(snap.to_dict() or {}, now, limit, window)
        if allowed:
            txn.set(ref, new_state)
        return allowed

    try:
        allowed = _run(db.transaction())
    except Exception:  # noqa: BLE001 — storage errors must not break the request path
        log.warning("Firestore quota check failed; allowing request", exc_info=True)
        return

    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "quota_exceeded",
                "message": (
                    f"search limit reached ({limit} per "
                    f"{settings.quota_window_sec}s); try again later"
                ),
            },
        )

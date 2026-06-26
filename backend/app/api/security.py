"""Request-level protection for the public API: a shared-secret API key and a
lightweight per-IP rate limiter. Both are FastAPI dependencies (SECURITY.md rec #3).

The API key is verified server-side; the browser never sees it — the Next.js
frontend proxies requests and attaches the key from a server-only env var.
"""

from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque

from fastapi import Depends, Header, HTTPException, Request

from app.config import Settings, get_settings


def require_api_key(
    x_api_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """Constant-time check of the `X-API-Key` header. No-op when no key is
    configured (local dev), so it is enforced only where `API_KEY` is set."""
    expected = settings.api_key
    if not expected:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "invalid or missing API key"},
        )


# Per-IP sliding-window counter. In-memory and therefore per-instance/best-effort —
# acceptable because Cloud Run is capped at a few instances; a distributed limiter
# (Redis) would be the next step for higher scale.
_HITS: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    limit = settings.rate_limit_per_min
    if limit <= 0:
        return
    now = time.monotonic()
    dq = _HITS[_client_ip(request)]
    while dq and now - dq[0] > 60.0:
        dq.popleft()
    if len(dq) >= limit:
        raise HTTPException(
            status_code=429,
            detail={"code": "rate_limited", "message": "too many requests; slow down"},
        )
    dq.append(now)
    if len(_HITS) > 10_000:  # opportunistic prune of idle IPs
        for ip in [k for k, v in _HITS.items() if not v]:
            del _HITS[ip]

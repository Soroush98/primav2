"""Structured search-event logging. Emits one JSON line per query to stdout, which
Cloud Run forwards to Cloud Logging as a parsed `jsonPayload` — query it in Logs
Explorer with `jsonPayload.event="search"` (and filter/group by `jsonPayload.client_ip`
or `jsonPayload.question`).

It writes a bare JSON line (not via `logging`) on purpose: Cloud Logging only parses
fields when the whole stdout line is valid JSON, and it promotes the special `severity`
field to the entry's level.

Privacy: this records raw user queries + client IPs. Keep log retention short (the
default `_Default` bucket is 30 days) or hash the IP if you don't need it in the clear.
"""

from __future__ import annotations

import json
import sys

_MAX_Q = 2000  # cap logged query length so a pathological input can't bloat logs


def log_search(question: str, detector: str | None, client_ip: str) -> None:
    line = json.dumps(
        {
            "severity": "INFO",
            "event": "search",
            "question": question[:_MAX_Q],
            "detector": detector,
            "client_ip": client_ip,
        },
        ensure_ascii=False,
    )
    print(line, file=sys.stdout, flush=True)

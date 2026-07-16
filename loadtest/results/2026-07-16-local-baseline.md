# 2026-07-16 — local baseline (health-ramp + burst-rejections)

| | |
|---|---|
| **Environment** | local dev laptop (Apple Silicon, macOS), uvicorn single process, loopback network — NOT Cloud Run; establishes the app-code floor, excludes network + cold-start + scaling effects |
| **Revision** | working tree on top of `09eb083` |
| **Commands** | `PEAK_RPS=50 RAMP=15s HOLD=30s k6 run health-ramp.js` · `DURATION=20s k6 run burst-rejections.js` (backend started with `API_KEY=local-perf-key`) |

## health-ramp (load): PASS

2,662 requests ramping 5→50 RPS, 0 failures.

| metric | value | SLO |
|---|---|---|
| p95 latency | **1.21 ms** | < 500 ms ✅ |
| p90 / med / max | 1.15 ms / 0.89 ms / 4.13 ms | |
| error rate | 0% | 0 ✅ |

## burst-rejections (spike on the protection chain): PASS

701 requests over 20 s — 30 RPS wrong-API-key + 5 RPS valid-key/invalid-body from
one IP. 100% of responses were the *correct* rejection (401, or 422→429 as the
rate-limit window filled); zero 5xx.

| metric | value | SLO |
|---|---|---|
| bad_key p95 | **2.93 ms** | < 300 ms ✅ |
| over_limit p95 | **4.1 ms** | < 300 ms ✅ |
| correct-status checks | 100% (701/701) | 100% ✅ |

## Interpretation

- App-code overhead on the rejection paths is single-digit milliseconds — the
  production p95 against Cloud Run will be dominated by network RTT and (at the
  tail) cold starts, which is what the same scripts measure when pointed at the
  service URL.
- The auth → rate-limit → quota chain never leaked a 5xx under burst, and
  rejected traffic costs ~3 ms of CPU — the protection is cheaper than the
  attack, as it must be.
- Next run worth recording: the same two scripts against the Cloud Run URL, plus
  a deliberate short `soak-analyze.js` against staging (real spend) to baseline
  the LLM-bound p95 before tightening its 45 s SLO.

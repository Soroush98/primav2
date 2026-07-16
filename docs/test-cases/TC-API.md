# TC-API — API contract, validation & protection

Automation: [backend/tests/test_api_contract.py](../../backend/tests/test_api_contract.py),
[backend/tests/test_api.py](../../backend/tests/test_api.py),
[backend/tests/test_quota.py](../../backend/tests/test_quota.py). All run in CI.

Format: **Given / When / Then**. Priority follows QA-STRATEGY §2 (R4, R5).

| ID | Title | Req | Pri | Given / When / Then | Automation |
|----|-------|-----|-----|---------------------|------------|
| TC-API-01 | Question at max length accepted | REQ-05 | P2 | Given a 2000-char question (BVA: max) / When POSTed to `/api/analyze` / Then 200 with a briefing | `test_question_at_max_length_accepted` |
| TC-API-02 | Question over max rejected | REQ-05 | P2 | Given 2001 chars (BVA: max+1) / When POSTed / Then 422 naming the failing field — never silent truncation | `test_question_over_max_length_rejected` |
| TC-API-03 | Empty question rejected | REQ-05 | P2 | Given `""` (BVA: min−1) / When POSTed / Then 422 | `test_question_empty_rejected` |
| TC-API-04 | Missing question rejected | REQ-05 | P2 | Given `{}` / When POSTed / Then 422 | `test_question_missing_rejected` |
| TC-API-05 | Non-JSON body rejected | REQ-05 | P3 | Given a text/plain body / When POSTed / Then 422 | `test_non_json_body_rejected` |
| TC-API-06 | Every documented detector mode accepted | REQ-02 | P1 | Given each of auto/baseline/omnianomaly/forecast (EP: valid partitions) / When POSTed / Then 200 | `test_every_documented_detector_mode_accepted` |
| TC-API-07 | Unknown detector mode rejected | REQ-02 | P2 | Given `detector:"quantum"` (EP: invalid) / When POSTed / Then 422, no coercion | `test_unknown_detector_mode_rejected` |
| TC-API-08 | Wrong API key → 401 with stable shape | REQ-04 | P1 | Given `API_KEY` configured and a wrong `X-API-Key` / When POSTed / Then 401 `{code:"unauthorized"}` and the submitted key is not echoed | `test_wrong_api_key_401_with_stable_error_shape` |
| TC-API-09 | Health endpoint needs no auth | REQ-04 | P1 | Given `API_KEY` configured / When GET `/api/health` / Then 200 (liveness must never 401) | `test_health_requires_no_auth` |
| TC-API-10 | Burst over rate limit → 429 with stable shape | REQ-04 | P1 | Given limit 2/min for one IP / When 3 requests / Then 200, 200, 429 `{code:"rate_limited"}` | `test_rate_limit_429_after_burst_with_stable_shape` |
| TC-API-11 | Rate-limit buckets are per IP | REQ-04 | P2 | Given IP A saturated / When IP B requests / Then B gets 200 | `test_rate_limit_buckets_are_per_ip` |
| TC-API-12 | OpenAPI contract snapshot | REQ-01, REQ-05 | P1 | Given `/openapi.json` / When compared to the published contract (paths, bounds, enum, response fields) / Then identical — proxy, e2e stub and k6 clients depend on it | `test_openapi_contract_pins_the_public_schema` |
| TC-API-13 | Quota window boundary correctness | REQ-04 | P1 | Given a full window / When elapsed == window (BVA edge) / Then reset; at window−ε still blocked; count never exceeds limit | `test_window_boundary_*`, `test_count_never_exceeds_limit_or_goes_negative` |
| TC-API-14 | Quota enforces per-IP 429 end-to-end | REQ-04 | P1 | Given quota 2/window (fake Firestore) / When a 3rd request from the same IP / Then 429 `{code:"quota_exceeded"}`, stored count not incremented, other IPs unaffected | `test_quota_blocks_with_429_after_limit`, `test_quota_is_tracked_per_ip` |
| TC-API-15 | Quota degrades open on store failure | REQ-04 | P1 | Given Firestore erroring (or quota disabled) / When requests arrive / Then 200 — a storage outage must never become an API outage, and disabled quota never constructs a client | `test_quota_degrades_open_when_store_errors`, `test_quota_disabled_never_touches_firestore` |

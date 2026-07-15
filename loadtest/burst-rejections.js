// Burst-tests the backend's protection chain: rejections must be fast, correct,
// and never 5xx. Costs nothing to run — no request ever reaches Gemini/BigQuery:
//   - bad_key:    wrong X-API-Key            -> 401 from require_api_key
//   - over_limit: valid key, invalid body    -> 422 (pydantic) until the per-IP
//                 sliding window fills, then -> 429 from rate_limit / quota_limit.
// The router-level deps (auth -> rate limit -> quota) run BEFORE body validation,
// so the invalid body exercises the whole chain without triggering the agent.
//
//   BASE_URL=http://127.0.0.1:8000 API_KEY=dev-key k6 run burst-rejections.js
import http from "k6/http";
import { check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:8000";
const API_KEY = __ENV.API_KEY || "";
const DURATION = __ENV.DURATION || "30s";
const BAD_KEY_RPS = Number(__ENV.BAD_KEY_RPS || 30);
const OVER_LIMIT_RPS = Number(__ENV.OVER_LIMIT_RPS || 5);
// Rejection latency budget; raise for high-RTT links to Cloud Run.
const REJECT_P95_MS = Number(__ENV.REJECT_P95_MS || 300);

export const options = {
  scenarios: {
    bad_key: {
      executor: "constant-arrival-rate",
      exec: "badKey",
      rate: BAD_KEY_RPS,
      timeUnit: "1s",
      duration: DURATION,
      preAllocatedVUs: 20,
      maxVUs: 100,
    },
    over_limit: {
      executor: "constant-arrival-rate",
      exec: "overLimit",
      rate: OVER_LIMIT_RPS,
      timeUnit: "1s",
      duration: DURATION,
      preAllocatedVUs: 5,
      maxVUs: 20,
    },
  },
  thresholds: {
    "http_req_duration{scenario:bad_key}": [`p(95)<${REJECT_P95_MS}`],
    "http_req_duration{scenario:over_limit}": [`p(95)<${REJECT_P95_MS}`],
    "checks{scenario:bad_key}": ["rate==1"],
    "checks{scenario:over_limit}": ["rate==1"],
  },
};

// question fails pydantic's min_length=1 -> guaranteed 422 ceiling, zero LLM cost.
const INVALID_BODY = JSON.stringify({ question: "", detector: "baseline" });

function post(headers) {
  return http.post(`${BASE_URL}/api/analyze`, INVALID_BODY, {
    headers: { "Content-Type": "application/json", ...headers },
    timeout: "10s",
  });
}

export function badKey() {
  const res = post({
    "X-API-Key": "definitely-not-the-key",
    "X-Real-Client-IP": "203.0.113.98",
  });
  // A 422 here means the server has no API_KEY configured — auth is off.
  check(res, { "rejected with 401": (r) => r.status === 401 });
}

export function overLimit() {
  const res = post({
    ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
    // One shared synthetic client IP -> all requests land in the same rate-limit
    // bucket, so the window fills deterministically and 429s must appear.
    "X-Real-Client-IP": "203.0.113.99",
  });
  check(res, {
    "422 (validation) or 429 (limited)": (r) => r.status === 422 || r.status === 429,
  });
}

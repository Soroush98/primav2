// Ramps request rate on /api/health to observe Cloud Run scaling behavior:
// cold-start latency on scale-out and what callers see when max-instances
// saturates. Free to run — the endpoint touches no external service.
//
//   BASE_URL=https://prima-backend-....run.app k6 run health-ramp.js
import http from "k6/http";
import { check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:8000";
const PEAK_RPS = Number(__ENV.PEAK_RPS || 50);
const RAMP = __ENV.RAMP || "30s";
const HOLD = __ENV.HOLD || "1m";
// Includes cold starts at the p99 tail; p95 should stay warm-path fast.
const P95_MS = Number(__ENV.P95_MS || 500);

export const options = {
  scenarios: {
    ramp: {
      executor: "ramping-arrival-rate",
      startRate: 5,
      timeUnit: "1s",
      preAllocatedVUs: 50,
      maxVUs: 200,
      stages: [
        { target: Math.ceil(PEAK_RPS / 2), duration: RAMP },
        { target: PEAK_RPS, duration: RAMP },
        { target: PEAK_RPS, duration: HOLD },
        { target: 0, duration: RAMP },
      ],
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: [`p(95)<${P95_MS}`],
  },
};

export default function () {
  const res = http.get(`${BASE_URL}/api/health`, { timeout: "10s" });
  check(res, { "status 200": (r) => r.status === 200 });
}

// Soak-tests the REAL analyze path: paced concurrent requests on the baseline
// detector arm, watching latency and error rate. Every iteration spends real money
// (Gemini calls + BigQuery bytes) — keep RATE_PER_MIN x DURATION deliberate, run it
// against a staging revision, and watch the Cloud Run memory dashboard while it
// runs (1 GiB x --concurrency=40 is the failure mode this test exists to catch).
//
//   BASE_URL=https://prima-backend-....run.app API_KEY=$BACKEND_API_KEY k6 run soak-analyze.js
import http from "k6/http";
import { check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:8000";
const API_KEY = __ENV.API_KEY || "";
const RATE_PER_MIN = Number(__ENV.RATE_PER_MIN || 20);
const DURATION = __ENV.DURATION || "5m";
// An analyze request is LLM-bound (multiple Gemini calls + a BigQuery scan);
// p95 under 45s is the default SLO — tighten once you have a baseline.
const P95_MS = Number(__ENV.P95_MS || 45_000);

const QUESTIONS = [
  "Give me a cluster health check — which machines look anomalous?",
  "Which machines show anomalous CPU and memory behaviour recently?",
  "Diagnose anomalous disk I/O across the fleet.",
];

export const options = {
  scenarios: {
    soak: {
      executor: "constant-arrival-rate",
      rate: RATE_PER_MIN,
      timeUnit: "1m",
      duration: DURATION,
      preAllocatedVUs: 10,
      maxVUs: 40,
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.02"],
    http_req_duration: [`p(95)<${P95_MS}`],
    checks: ["rate>0.98"],
  },
};

export function setup() {
  const m = /^(\d+)(s|m|h)$/.exec(DURATION);
  const minutes = m ? Number(m[1]) * { s: 1 / 60, m: 1, h: 60 }[m[2]] : NaN;
  const total = Number.isFinite(minutes) ? Math.round(RATE_PER_MIN * minutes) : "?";
  console.warn(
    `soak: ~${total} REAL analyze calls against ${BASE_URL} ` +
      "(Gemini + BigQuery spend). Ctrl+C now if that is not intended.",
  );
}

export default function () {
  const question = QUESTIONS[__ITER % QUESTIONS.length];
  const res = http.post(
    `${BASE_URL}/api/analyze`,
    JSON.stringify({ question, detector: "baseline" }),
    {
      headers: {
        "Content-Type": "application/json",
        ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
        // Per-VU synthetic visitor IP (trusted only behind the API key): spreads the
        // per-IP limiter/quota the way real distinct users would, so the soak measures
        // capacity rather than a single IP's rate limit.
        "X-Real-Client-IP": `203.0.113.${(__VU % 200) + 1}`,
      },
      timeout: "120s",
    },
  );
  check(res, {
    "status 200": (r) => r.status === 200,
    "briefing present, no error": (r) => {
      try {
        const body = r.json();
        return Boolean(body.briefing) && !body.error;
      } catch {
        return false;
      }
    },
  });
}

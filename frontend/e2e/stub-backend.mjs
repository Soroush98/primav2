// Minimal stand-in for the FastAPI backend, used by the Playwright smoke tests.
// Serves canned /api/analyze responses shaped like AnalyzeResponse (app/lib/api.ts)
// so the e2e run needs no GCP, Gemini, or torch. Rejects requests whose X-API-Key
// doesn't match, so a passing smoke test proves the Next proxy attaches the key.
import { createServer } from "node:http";

const port = Number(process.argv[2] ?? 4545);
const apiKey = process.argv[3] ?? "";

const SPIKES = { 30: 9.1, 31: 7.8, 64: 5.2 };
const POINTS = Array.from({ length: 96 }, (_, i) => ({
  i,
  score: SPIKES[i] ?? (i % 7) * 0.35 + 0.4,
  flag: SPIKES[i] != null,
}));

const baseline = (question) => ({
  question,
  briefing:
    "Fleet scan complete: 3 of 96 windows flagged; m_1043 is the top offender, driven by cpu_util_percent.",
  focus: { metric: "cpu" },
  sql: "SELECT machine_id, AVG(cpu_util_percent) AS cpu FROM `demo.windows` GROUP BY machine_id",
  detection: {
    n: 96,
    flagged: 3,
    threshold: 3.5,
    score_max: 9.1,
    detector: "baseline",
    top_windows: [
      { i: 30, label: "m_1043 · 12:00", score: 9.1 },
      { i: 31, label: "m_1043 · 12:30", score: 7.8 },
      { i: 64, label: "m_0871 · 04:00", score: 5.2 },
    ],
    points: POINTS,
  },
  root_cause: {
    ranked_features: [
      ["cpu_util_percent", 3.2],
      ["mem_util_percent", 1.4],
      ["net_in", 0.6],
    ],
  },
});

const hourly = (n, base) => Array.from({ length: n }, (_, i) => base + Math.sin(i / 5) * 6);

const forecast = (question) => ({
  question,
  briefing: "Chronos forecast ready: m_1043 cpu is expected to stay in band for the next 2 days.",
  focus: { metric: "cpu" },
  sql: "SELECT ts, cpu_util_percent FROM `demo.timeseries` WHERE machine_id = 'm_1043' ORDER BY ts",
  detection: {
    n: 2400,
    detector: "chronos",
    machine: "m_1043",
    horizon_hours: 48,
    forecast: {
      machine: "m_1043",
      horizon_hours: 48,
      features: {
        cpu: { history: hourly(72, 42), median: hourly(48, 44), lo: hourly(48, 38), hi: hourly(48, 50) },
        mem: { history: hourly(72, 61), median: hourly(48, 62), lo: hourly(48, 58), hi: hourly(48, 66) },
      },
    },
  },
  root_cause: null,
});

// Renderable "no data" response — the shape detector_baseline returns when the
// generated SQL matched nothing (see _empty_detection in backend nodes.py).
const empty = (question) => ({
  question,
  briefing: "No telemetry rows matched the query — nothing to score.",
  focus: { metric: "cpu" },
  sql: "SELECT machine_id, cpu FROM `demo.windows` WHERE 1 = 0",
  detection: { n: 0, flagged: 0, note: "no rows returned" },
  root_cause: null,
});

// FastAPI-shaped quota rejection (see backend app/api/quota.py) so e2e can assert
// the UI's behavior when a visitor exhausts the per-IP search quota.
const QUOTA_DETAIL = {
  detail: { code: "quota_exceeded", message: "search limit reached (10 per 86400s); try again later" },
};

const server = createServer((req, res) => {
  const send = (status, payload) => {
    res.writeHead(status, { "Content-Type": "application/json" });
    res.end(JSON.stringify(payload));
  };
  if (req.method === "GET" && req.url === "/api/health") return send(200, { status: "ok" });
  if (req.method !== "POST" || req.url !== "/api/analyze") return send(404, { detail: "not found" });
  if (apiKey && req.headers["x-api-key"] !== apiKey) return send(401, { detail: "invalid API key" });

  let body = "";
  req.on("data", (chunk) => (body += chunk));
  req.on("end", () => {
    const { question = "", detector = "auto" } = JSON.parse(body || "{}");
    if (/boom/i.test(question)) return send(503, { detail: "backend exploded (stub)" });
    if (/quota/i.test(question)) return send(429, QUOTA_DETAIL);
    if (/quiet fleet/i.test(question)) return send(200, empty(question));
    send(200, detector === "forecast" ? forecast(question) : baseline(question));
  });
});

server.listen(port, "127.0.0.1", () => {
  console.log(`stub backend listening on http://127.0.0.1:${port}`);
});

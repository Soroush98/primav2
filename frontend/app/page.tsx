"use client";

import { useEffect, useState } from "react";
import { analyze, type AnalyzeResponse, type DetectorMode } from "./lib/api";
import Architecture from "./components/Architecture";
import ScoreChart from "./components/ScoreChart";

const EXAMPLES = [
  "Give me a cluster health check — which machines look anomalous?",
  "Which machines show anomalous CPU and memory behaviour recently?",
  "Find machines with unusual network traffic spikes and summarize the top offenders.",
  "Diagnose anomalous disk I/O across the fleet.",
  "What is the most anomalous machine and its likely root cause?",
];

function fmt(v: number): string {
  const a = Math.abs(v);
  if (a >= 1000)
    return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(v);
  return v.toFixed(2);
}

type Status = "ok" | "warn" | "error";

export default function Home() {
  const [tab, setTab] = useState<"dashboard" | "architecture">("dashboard");
  const [question, setQuestion] = useState(EXAMPLES[1]);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detector, setDetector] = useState<DetectorMode>("auto");

  async function run(q: string) {
    setLoading(true);
    setError(null);
    try {
      setResult(await analyze(q, detector));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // Kick off the initial analysis once on mount so the dashboard isn't empty.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    run(question);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const det = result?.detection ?? null;
  const ranked = result?.root_cause?.ranked_features ?? [];
  const maxRank = ranked.length ? Math.max(...ranked.map(([, v]) => Math.abs(v)), 1e-9) : 1;
  const n = det?.n ?? 0;
  const flagged = det?.flagged ?? 0;
  const flagRate = n > 0 ? (flagged / n) * 100 : 0;

  const trace: { agent: string; status: Status; detail: string }[] = result
    ? [
        { agent: "orchestrator", status: result.focus ? "ok" : "warn", detail: "intent parsed" },
        {
          agent: "sql_analyst",
          status: result.error ? "error" : result.sql ? "ok" : "warn",
          detail: result.error ? "query failed" : `${n.toLocaleString()} rows from BigQuery`,
        },
        {
          agent: "detector",
          status: n > 0 ? "ok" : "warn",
          detail:
            n > 0
              ? `${det?.detector ?? "baseline"} · flagged ${flagged} of ${n.toLocaleString()}`
              : det?.note ?? "no rows",
        },
        {
          agent: "root_cause",
          status: ranked.length ? "ok" : "warn",
          detail: ranked.length ? `top driver: ${ranked[0][0]}` : "no features",
        },
        { agent: "narrator", status: result.briefing ? "ok" : "warn", detail: "briefing ready" },
      ]
    : [];

  return (
    <div className="wrap">
      <div className="header">
        <div className="title">
          Prima<span className="dot">.</span>{" "}
          <span className="muted" style={{ fontSize: 16, fontWeight: 400 }}>
            Agentic Server-Health Intelligence
          </span>
        </div>
        <span className="badge live">● Live Gemini agents · BigQuery</span>
      </div>
      <div className="subtitle">
        A LangGraph agent fleet that autonomously writes read-only SQL, detects anomalies, and
        diagnoses root cause over <strong>Alibaba cluster-trace-v2018</strong> telemetry (~247M
        samples) in BigQuery — reasoned by Gemini 2.5 Flash on Vertex AI.
      </div>

      <div className="tabs">
        <button className={`tab ${tab === "dashboard" ? "active" : ""}`} onClick={() => setTab("dashboard")}>
          Dashboard
        </button>
        <button className={`tab ${tab === "architecture" ? "active" : ""}`} onClick={() => setTab("architecture")}>
          Architecture
        </button>
      </div>

      {tab === "architecture" && <Architecture />}

      {tab === "dashboard" && (
        <>
          <div className="ask">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !loading && run(question)}
              placeholder="Ask about a machine's health, anomalies, or root cause…"
            />
            <select
              value={detector}
              onChange={(e) => setDetector(e.target.value as DetectorMode)}
              disabled={loading}
              title="Detector arm — Auto picks by data shape; OmniAnomaly forces the temporal model"
            >
              <option value="auto">Auto</option>
              <option value="baseline">Baseline (snapshot)</option>
              <option value="omnianomaly">OmniAnomaly (temporal)</option>
            </select>
            <button onClick={() => run(question)} disabled={loading || !question.trim()}>
              {loading ? <span className="spinner" /> : "Analyze"}
            </button>
          </div>
          <div className="chips">
            {EXAMPLES.map((ex) => (
              <button key={ex} type="button" className="chip" onClick={() => { setQuestion(ex); run(ex); }}>
                {ex}
              </button>
            ))}
          </div>

          {error && (
            <div className="card error-card" style={{ marginBottom: 16 }}>
              <strong style={{ color: "var(--bad)" }}>Error:</strong> {error}
              <div className="muted" style={{ marginTop: 6 }}>
                Is the backend running? <code>uv run fastapi dev app/main.py</code> in <code>backend/</code>.
              </div>
            </div>
          )}

          {result && !error && (
            <>
              <div className="grid cols-3" style={{ marginBottom: 16 }}>
                <div className="card">
                  <h3>Windows analyzed</h3>
                  <div className="kpi">{n.toLocaleString()}</div>
                </div>
                <div className="card">
                  <h3>Anomalies flagged</h3>
                  <div className={`kpi ${flagged > 0 ? "warn" : "good"}`}>{flagged.toLocaleString()}</div>
                </div>
                <div className="card">
                  <h3>Flag rate</h3>
                  <div className="kpi">{flagRate.toFixed(1)}<small> %</small></div>
                </div>
              </div>

              <div className="grid cols-2">
                <div className="card">
                  <h3>Briefing</h3>
                  <p className="summary">{result.briefing || "—"}</p>
                </div>
                <div className="card">
                  <h3>Agent trace</h3>
                  <div className="trace">
                    {trace.map((t) => (
                      <div key={t.agent} className={`trace-row ${t.status}`}>
                        <span className={`dot-status ${t.status}`} />
                        <span className="trace-agent">{t.agent}</span>
                        <span className="trace-detail">{t.detail}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {det?.points && det.points.length > 0 && (
                <>
                  <div className="section-title">Anomaly windows</div>
                  <div className="card">
                    <ScoreChart det={det} />
                    {det.top_windows && det.top_windows.length > 0 && (
                      <div style={{ marginTop: 14 }}>
                        <h3>Top flagged windows</h3>
                        <div className="chips">
                          {det.top_windows.map((w) => (
                            <span
                              key={w.i}
                              className="chip"
                              style={{ color: "var(--bad)", borderColor: "#5e1e1e", cursor: "default" }}
                            >
                              {w.label} · {fmt(w.score)}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </>
              )}

              {ranked.length > 0 && (
                <>
                  <div className="section-title">Root cause — top metric deviations</div>
                  <div className="card">
                    <div className="bars">
                      {ranked.map(([name, val]) => (
                        <div className="bar-row" key={name}>
                          <span className="bar-label">{name}</span>
                          <span className="bar-track">
                            <span
                              className="bar-fill"
                              style={{ width: `${Math.max(2, (Math.abs(val) / maxRank) * 100)}%` }}
                            />
                          </span>
                          <span className="bar-val">{fmt(val)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </>
              )}

              {result.sql && (
                <>
                  <div className="section-title">Generated SQL (read-only)</div>
                  <div className="card">
                    <pre className="sql">{result.sql}</pre>
                  </div>
                </>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}

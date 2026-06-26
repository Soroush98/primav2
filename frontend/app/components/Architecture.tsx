const NODES = [
  { name: "orchestrator", role: "Parses the question into structured intent (focus + entities).", tag: "Gemini" },
  { name: "sql_analyst", role: "Writes ONE read-only SQL, guards it (SELECT/WITH only), runs it.", tag: "Gemini · BigQuery" },
  { name: "detector", role: "Scores each row with the MAD/EVT baseline; grades if labels exist.", tag: "NumPy / SciPy" },
  { name: "root_cause", role: "Ranks the metrics that drove the top anomalies (MAD deviation).", tag: "NumPy" },
  { name: "narrator", role: "Turns the evidence into a human briefing.", tag: "Gemini" },
];

const CLOUD = [
  ["BigQuery", "primav2.alibaba_cluster — 247M raw samples + 8.4M 5-min bins"],
  ["Vertex AI · Gemini 2.5 Flash", "reasoning engine (orchestrator, sql_analyst, narrator)"],
  ["Cloud Run", "stateless FastAPI host (target deployment)"],
  ["Auth", "Application Default Credentials — no API keys"],
];

export default function Architecture() {
  return (
    <div className="arch">
      <div className="card">
        <h3>Agent fleet (LangGraph)</h3>
        <div className="flow">
          {NODES.map((n, i) => (
            <div key={n.name} style={{ display: "contents" }}>
              <div className="node">
                <div className="n-name">{n.name}</div>
                <div className="n-role">{n.role}</div>
                <span className="n-tag">{n.tag}</span>
              </div>
              {i < NODES.length - 1 && <div className="arrow">→</div>}
            </div>
          ))}
        </div>
        <div className="legend">
          <span><i style={{ background: "var(--accent)" }} /> Gemini (Vertex AI)</span>
          <span><i style={{ background: "var(--good)" }} /> BigQuery</span>
          <span><i style={{ background: "var(--muted)" }} /> in-process NumPy</span>
        </div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h3>What runs on Google Cloud</h3>
          {CLOUD.map(([k, v]) => (
            <div className="kv" key={k}>
              <span className="k">{k}</span>
              <span className="v">{v}</span>
            </div>
          ))}
        </div>
        <div className="card">
          <h3>Request path</h3>
          <p className="summary" style={{ fontSize: 14 }}>
            Browser → <code>POST /api/analyze</code> → FastAPI → the five nodes run in sequence.
            The only paid calls in the request path are managed Gemini API calls and BigQuery
            queries — there are <strong>no persistent Vertex endpoints</strong>. The OmniAnomaly
            comparison arm is trained offline; the shipped detector is the cheap MAD/EVT baseline.
          </p>
        </div>
      </div>
    </div>
  );
}

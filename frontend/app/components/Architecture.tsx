// Linear pipeline; the detector step is a CONDITIONAL ROUTE that fans out to 3 arms.
const LINEAR = [
  { name: "orchestrator", role: "Parses the question into structured intent (focus + entities).", tag: "Gemini" },
  { name: "sql_analyst", role: "Writes ONE read-only SQL (snapshot vs per-machine series, by mode); guards + runs it.", tag: "Gemini · BigQuery" },
  { name: "route_detector", role: "Conditional edge — picks the detector arm by mode + data shape.", tag: "router" },
  { name: "root_cause", role: "Ranks the metrics that drove the top anomalies (MAD deviation).", tag: "NumPy" },
  { name: "narrator", role: "Turns the evidence into a human briefing.", tag: "Gemini" },
];

const ARMS = [
  { name: "detector_baseline", role: "MAD/EVT robust z-score + POT — order-invariant, fleet snapshots.", tag: "NumPy / SciPy" },
  { name: "detector_omni", role: "OmniAnomaly VAE — windows each machine's series for temporal anomalies.", tag: "PyTorch" },
  { name: "detector_forecast", role: "Chronos-Bolt zero-shot forecast residuals on a machine's series.", tag: "transformers" },
];

const CLOUD = [
  ["BigQuery", "primav2.alibaba_cluster — 247M raw samples + 8.4M 5-min bins"],
  ["Vertex AI · Gemini 2.5 Flash", "reasoning engine (orchestrator, sql_analyst, narrator)"],
  ["Detectors", "MAD/EVT baseline + OmniAnomaly (trained offline) + Chronos-Bolt (zero-shot) — served on demand"],
  ["Cloud Run", "stateless FastAPI host — live (CI/CD, one warm instance)"],
  ["Auth", "Application Default Credentials — no API keys"],
];

export default function Architecture() {
  return (
    <div className="arch">
      <div className="card">
        <h3>Agent fleet (LangGraph) — conditional detector route</h3>
        <div className="flow">
          {LINEAR.map((n, i) => (
            <div key={n.name} style={{ display: "contents" }}>
              <div className={`node ${n.tag === "router" ? "node-route" : ""}`}>
                <div className="n-name">{n.name}</div>
                <div className="n-role">{n.role}</div>
                <span className="n-tag">{n.tag}</span>
              </div>
              {i < LINEAR.length - 1 && <div className="arrow">→</div>}
            </div>
          ))}
        </div>

        <div className="arms">
          <div className="arms-label">
            ⤷ <code>route_detector</code> picks <strong>one arm</strong> (UI selector, or
            <strong> Auto</strong> by data shape); all arms converge back into <code>root_cause</code>:
          </div>
          <div className="arms-row">
            {ARMS.map((a) => (
              <div className="node arm" key={a.name}>
                <div className="n-name">{a.name}</div>
                <div className="n-role">{a.role}</div>
                <span className="n-tag">{a.tag}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="legend">
          <span><i style={{ background: "var(--accent)" }} /> Gemini (Vertex AI)</span>
          <span><i style={{ background: "var(--good)" }} /> BigQuery</span>
          <span><i style={{ background: "var(--muted)" }} /> in-process (NumPy / PyTorch)</span>
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
            Browser → <code>POST /api/analyze</code> → FastAPI → the fleet runs:
            orchestrator → sql_analyst → <strong>⟨route_detector⟩</strong> →{" "}
            <strong>{"{ baseline | OmniAnomaly | Chronos }"}</strong> → root_cause → narrator.
            The arm is chosen by the detector selector (or <strong>Auto</strong>, by data shape).
            The only paid calls are managed Gemini API calls and BigQuery queries — there are{" "}
            <strong>no persistent Vertex endpoints</strong>: OmniAnomaly is trained offline then
            loaded at startup, Chronos-Bolt is zero-shot.
          </p>
        </div>
      </div>
    </div>
  );
}

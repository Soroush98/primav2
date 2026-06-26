"use client";

import type { Detection } from "../lib/api";

// Chronos forecast view: the machine's actual series vs the model's forecast band
// (q10–q90) for the top-deviating feature. The flagged bins are where the actual
// deviated most from the forecast RELATIVE TO the predicted band — each is shown as
// a ringed dot with a drop-line back to the forecast median (the gap the model
// missed). Anomaly = surprise vs predicted uncertainty, not raw spike size.
export default function ForecastChart({ det }: { det: Detection }) {
  const fc = det.forecast;
  if (!fc || !fc.actual?.length) return null;
  const { actual, median, lo, hi, score, threshold, feature } = fc;
  const n = actual.length;

  const W = 1000;
  const H = 240;
  const PAD = 34;
  const vals = [...actual, ...lo, ...hi];
  const vMin = Math.min(...vals);
  const span = Math.max(...vals) - vMin || 1e-9;
  const x = (i: number) => PAD + (i / Math.max(n - 1, 1)) * (W - 2 * PAD);
  const y = (v: number) => H - PAD - ((v - vMin) / span) * (H - 2 * PAD);
  const poly = (arr: number[]) => arr.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  const band = [
    ...hi.map((v, i) => `${x(i)},${y(v)}`),
    ...lo.map((v, i) => `${x(i)},${y(v)}`).reverse(),
  ].join(" ");
  const flagged = actual.map((_, i) => score[i] >= threshold);

  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>
        <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="var(--border)" />
        <line x1={PAD} y1={PAD} x2={PAD} y2={H - PAD} stroke="var(--border)" />

        {/* forecast band (q10–q90) */}
        <polygon points={band} fill="var(--accent)" opacity={0.14} />
        {/* forecast median */}
        <polyline points={poly(median)} fill="none" stroke="var(--accent)" strokeWidth={1.3} opacity={0.85} strokeDasharray="5 4" />
        {/* actual */}
        <polyline points={poly(actual)} fill="none" stroke="var(--text)" strokeWidth={1.5} opacity={0.85} />

        {/* flagged bins: drop-line from forecast median to actual + ringed dot */}
        {actual.map((v, i) => (flagged[i] ? (
          <g key={i}>
            <line x1={x(i)} y1={y(median[i])} x2={x(i)} y2={y(v)} stroke="var(--bad)" strokeWidth={1.3} opacity={0.8} />
            <circle cx={x(i)} cy={y(v)} r={5} fill="var(--bad)" stroke="var(--text)" strokeWidth={1.4} />
          </g>
        ) : null))}

        {/* legend */}
        <g transform={`translate(${PAD + 6}, ${PAD - 6})`} fontSize="11">
          <line x1={0} y1={0} x2={18} y2={0} stroke="var(--text)" strokeWidth={1.6} />
          <text x={24} y={4} fill="var(--muted)">actual</text>
          <rect x={86} y={-5} width={18} height={9} fill="var(--accent)" opacity={0.22} />
          <text x={110} y={4} fill="var(--muted)">forecast q10–q90</text>
          <circle cx={236} cy={0} r={4} fill="var(--bad)" stroke="var(--text)" strokeWidth={1.2} />
          <text x={246} y={4} fill="var(--muted)">flagged (off-forecast)</text>
        </g>

        <text x={W / 2} y={H - 6} textAnchor="middle" fontSize="11" fill="var(--muted)">
          bin (recent window)
        </text>
        <text x={12} y={PAD - 12} fontSize="11" fill="var(--muted)">
          {feature}
        </text>
      </svg>

      <p className="muted" style={{ fontSize: 12, marginTop: 10, lineHeight: 1.55 }}>
        Red rings are the flagged bins — where the actual deviated most from the forecast{" "}
        <em>relative to the model&apos;s predicted band</em> (the line shows the gap to the forecast
        median). It&apos;s surprise vs. predicted uncertainty, not raw spike size: a tall spike
        inside a wide band isn&apos;t anomalous, but a smaller move the model was confident about is.
        Flagging is the <strong>joint</strong> residual across all 5 metrics; <strong>{feature}</strong>{" "}
        is shown as the top contributor.
      </p>
    </>
  );
}

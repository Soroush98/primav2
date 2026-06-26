"use client";

import type { Detection } from "../lib/api";

// Chronos forecast view: the machine's actual series vs the model's forecast band
// (q10–q90) for the top-deviating feature. Red dots mark bins flagged as anomalous
// (aggregate forecast residual at/above the POT threshold) — i.e. where the actual
// leaves what the model predicted. This is what the score scatter can't show.
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
  // closed band: q90 forward, then q10 backward
  const band = [
    ...hi.map((v, i) => `${x(i)},${y(v)}`),
    ...lo.map((v, i) => `${x(i)},${y(v)}`).reverse(),
  ].join(" ");

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>
      {/* axes */}
      <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="var(--border)" />
      <line x1={PAD} y1={PAD} x2={PAD} y2={H - PAD} stroke="var(--border)" />

      {/* forecast band (q10–q90) */}
      <polygon points={band} fill="var(--accent)" opacity={0.16} />
      {/* forecast median */}
      <polyline points={poly(median)} fill="none" stroke="var(--accent)" strokeWidth={1.4} opacity={0.85} strokeDasharray="5 4" />
      {/* actual */}
      <polyline points={poly(actual)} fill="none" stroke="var(--text)" strokeWidth={1.6} />
      {/* flagged bins: actual where the aggregate residual crossed the threshold */}
      {actual.map((v, i) => (score[i] >= threshold ? (
        <circle key={i} cx={x(i)} cy={y(v)} r={3.6} fill="var(--bad)" opacity={0.95} />
      ) : null))}

      {/* legend */}
      <g transform={`translate(${PAD + 6}, ${PAD - 6})`} fontSize="11">
        <line x1={0} y1={0} x2={18} y2={0} stroke="var(--text)" strokeWidth={1.6} />
        <text x={24} y={4} fill="var(--muted)">actual</text>
        <rect x={86} y={-5} width={18} height={9} fill="var(--accent)" opacity={0.25} />
        <text x={110} y={4} fill="var(--muted)">forecast q10–q90</text>
        <circle cx={232} cy={0} r={3.4} fill="var(--bad)" />
        <text x={242} y={4} fill="var(--muted)">flagged</text>
      </g>

      <text x={W / 2} y={H - 6} textAnchor="middle" fontSize="11" fill="var(--muted)">
        bin (recent window)
      </text>
      <text x={12} y={PAD - 12} fontSize="11" fill="var(--muted)">
        {feature}
      </text>
    </svg>
  );
}

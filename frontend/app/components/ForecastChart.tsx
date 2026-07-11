"use client";

import { useState } from "react";
import type { Detection } from "../lib/api";

// Chronos forecast view: the machine's recent hourly history (solid line), then the
// model's zero-shot forecast for the next 2 days — median (dashed) inside the
// q10–q90 uncertainty band. Forecast only: this arm does no anomaly flagging.
export default function ForecastChart({ det }: { det: Detection }) {
  const [selected, setSelected] = useState("cpu");
  const fc = det.forecast;
  if (!fc?.features) return null;
  const names = Object.keys(fc.features);
  if (names.length === 0) return null;
  const feature = fc.features[selected] ? selected : names[0];
  const { history, median, lo, hi } = fc.features[feature];
  const nH = history.length;
  const n = nH + median.length;
  const days = Math.round(median.length / 24);

  const W = 1000;
  const H = 240;
  const PAD = 34;
  const vals = [...history, ...lo, ...hi];
  const vMin = Math.min(...vals);
  const span = Math.max(...vals) - vMin || 1e-9;
  const x = (i: number) => PAD + (i / Math.max(n - 1, 1)) * (W - 2 * PAD);
  const y = (v: number) => H - PAD - ((v - vMin) / span) * (H - 2 * PAD);
  const poly = (arr: number[], off = 0) => arr.map((v, i) => `${x(i + off)},${y(v)}`).join(" ");
  const band = [
    ...hi.map((v, i) => `${x(i + nH)},${y(v)}`),
    ...lo.map((v, i) => `${x(i + nH)},${y(v)}`).reverse(),
  ].join(" ");
  const nowX = x(nH - 1);

  return (
    <>
      <div className="chips" style={{ marginBottom: 10 }}>
        {names.map((name) => (
          <button
            key={name}
            type="button"
            className="chip"
            onClick={() => setSelected(name)}
            style={name === feature ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}
          >
            {name}
          </button>
        ))}
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>
        <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="var(--border)" />
        <line x1={PAD} y1={PAD} x2={PAD} y2={H - PAD} stroke="var(--border)" />

        {/* "now" divider: history to the left, forecast to the right */}
        <line x1={nowX} y1={PAD} x2={nowX} y2={H - PAD} stroke="var(--muted)" strokeDasharray="3 4" opacity={0.7} />
        <text x={nowX + 4} y={PAD + 4} fontSize="10" fill="var(--muted)">now</text>

        {/* forecast band (q10–q90) */}
        <polygon points={band} fill="var(--accent)" opacity={0.14} />
        {/* forecast median — anchored to the last history point for continuity */}
        <polyline
          points={poly([history[nH - 1], ...median], nH - 1)}
          fill="none"
          stroke="var(--accent)"
          strokeWidth={1.3}
          opacity={0.85}
          strokeDasharray="5 4"
        />
        {/* hourly history */}
        <polyline points={poly(history)} fill="none" stroke="var(--text)" strokeWidth={1.5} opacity={0.85} />

        {/* legend */}
        <g transform={`translate(${PAD + 6}, ${PAD - 6})`} fontSize="11">
          <line x1={0} y1={0} x2={18} y2={0} stroke="var(--text)" strokeWidth={1.6} />
          <text x={24} y={4} fill="var(--muted)">history (hourly)</text>
          <line x1={116} y1={0} x2={134} y2={0} stroke="var(--accent)" strokeWidth={1.4} strokeDasharray="5 4" />
          <text x={140} y={4} fill="var(--muted)">forecast median</text>
          <rect x={238} y={-5} width={18} height={9} fill="var(--accent)" opacity={0.22} />
          <text x={262} y={4} fill="var(--muted)">q10–q90 band</text>
        </g>

        <text x={W / 2} y={H - 6} textAnchor="middle" fontSize="11" fill="var(--muted)">
          {nH}h of history → next {days} days (hourly)
        </text>
        <text x={12} y={PAD - 12} fontSize="11" fill="var(--muted)">
          {feature} · {fc.machine}
        </text>
      </svg>

      <p className="muted" style={{ fontSize: 12, marginTop: 10, lineHeight: 1.55 }}>
        Zero-shot Chronos-Bolt forecast of <strong>{fc.machine}</strong>&apos;s{" "}
        <strong>{feature}</strong> for the next {days} days, from its 5-min telemetry
        resampled to hourly means. The dashed line is the median forecast; the shaded band is
        the model&apos;s q10–q90 uncertainty, which widens with the horizon. This arm only
        forecasts — no anomaly detection or flagging is performed.
      </p>
    </>
  );
}

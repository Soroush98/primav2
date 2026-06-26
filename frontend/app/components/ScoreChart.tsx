"use client";

import type { Detection } from "../lib/api";

// Anomaly-score scatter: each window is a point at (window index, score); points
// at or above the EVT/POT threshold are the red "dots" (flagged anomalies).
export default function ScoreChart({ det }: { det: Detection }) {
  const pts = det.points ?? [];
  if (!pts.length) return null;

  const W = 1000;
  const H = 240;
  const PAD = 34;
  const maxI = Math.max(...pts.map((p) => p.i), 1);
  const maxS = Math.max(det.score_max ?? 0, det.threshold ?? 0, ...pts.map((p) => p.score), 1e-9);
  const x = (i: number) => PAD + (i / maxI) * (W - 2 * PAD);
  const y = (s: number) => H - PAD - (s / maxS) * (H - 2 * PAD);
  const thrY = det.threshold != null ? y(det.threshold) : null;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>
      {/* axes */}
      <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="var(--border)" />
      <line x1={PAD} y1={PAD} x2={PAD} y2={H - PAD} stroke="var(--border)" />

      {/* threshold */}
      {thrY != null && (
        <>
          <line x1={PAD} y1={thrY} x2={W - PAD} y2={thrY} stroke="var(--warn)" strokeWidth={1.5} strokeDasharray="6 5" />
          <text x={W - PAD} y={thrY - 6} textAnchor="end" fontSize="11" fill="var(--warn)">
            POT threshold {det.threshold!.toFixed(2)}
          </text>
        </>
      )}

      {/* points: normal (muted) then flagged (red dots) on top */}
      {pts.filter((p) => !p.flag).map((p, k) => (
        <circle key={`n${k}`} cx={x(p.i)} cy={y(p.score)} r={1.6} fill="var(--muted)" opacity={0.45} />
      ))}
      {pts.filter((p) => p.flag).map((p, k) => (
        <circle key={`f${k}`} cx={x(p.i)} cy={y(p.score)} r={3.6} fill="var(--bad)" opacity={0.95} />
      ))}

      <text x={W / 2} y={H - 6} textAnchor="middle" fontSize="11" fill="var(--muted)">
        window index
      </text>
      <text x={12} y={PAD - 12} fontSize="11" fill="var(--muted)">
        anomaly score
      </text>
    </svg>
  );
}

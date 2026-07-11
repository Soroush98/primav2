export interface ScorePoint {
  i: number;
  score: number;
  flag: boolean;
}
export interface TopWindow {
  i: number;
  label: string;
  score: number;
}
export interface Detection {
  n: number;
  flagged?: number;    // anomaly arms only — absent on Chronos forecast runs
  threshold?: number;
  score_max?: number;
  detector?: string;   // which arm ran: "baseline" | "omnianomaly" | "chronos"
  machine?: string;         // Chronos arm: the machine that was forecast
  horizon_hours?: number;   // Chronos arm: forecast horizon (48 = 2 days)
  forecast?: ForecastDetail;  // Chronos arm only: hourly history + 2-day forecast
  top_windows?: TopWindow[];
  points?: ScorePoint[];
  note?: string;
  grade?: Record<string, number> | null;
}

export type DetectorMode = "auto" | "baseline" | "omnianomaly" | "forecast";

export interface FeatureForecast {
  history: number[]; // hourly means of the machine's recent series
  median: number[];  // q50 forecast, one point per hour ahead
  lo: number[];      // q10
  hi: number[];      // q90
}

export interface ForecastDetail {
  machine: string;
  horizon_hours: number;
  features: Record<string, FeatureForecast>;
}

export interface RootCause {
  ranked_features?: [string, number][];
}

export interface AnalyzeResponse {
  question: string;
  briefing: string;
  focus?: Record<string, unknown> | null;
  sql?: string | null;
  detection?: Detection | null;
  root_cause?: RootCause | null;
  error?: string | null;
}

export async function analyze(
  question: string,
  detector: DetectorMode = "auto",
): Promise<AnalyzeResponse> {
  // Same-origin: hits the Next.js route handler, which proxies to the backend
  // server-side and adds the API key (kept out of the browser).
  const res = await fetch(`/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, detector }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Request failed (${res.status}): ${detail}`);
  }
  return res.json() as Promise<AnalyzeResponse>;
}

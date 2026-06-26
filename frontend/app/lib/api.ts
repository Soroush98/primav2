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
  flagged: number;
  threshold?: number;
  score_max?: number;
  detector?: string;   // which arm ran: "baseline" | "omnianomaly"
  top_windows?: TopWindow[];
  points?: ScorePoint[];
  note?: string;
  grade?: Record<string, number> | null;
}

export type DetectorMode = "auto" | "baseline" | "omnianomaly" | "forecast";

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

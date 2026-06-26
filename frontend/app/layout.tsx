import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Prima — Agentic Server-Health Intelligence",
  description:
    "A LangGraph agent fleet that writes SQL, detects anomalies, and diagnoses root cause over cluster telemetry in BigQuery, powered by Gemini on Vertex AI.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

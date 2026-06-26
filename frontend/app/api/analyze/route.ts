import { NextRequest, NextResponse } from "next/server";

// Server-side proxy: the browser calls this same-origin route; this handler
// forwards to the FastAPI backend and attaches the API key from a server-only
// env var — so the secret never reaches the client.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const backend = process.env.BACKEND_URL;
  if (!backend) {
    return NextResponse.json({ error: "BACKEND_URL is not configured" }, { status: 500 });
  }
  const key = process.env.BACKEND_API_KEY;
  const body = await req.text();
  const res = await fetch(`${backend}/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(key ? { "X-API-Key": key } : {}) },
    body,
  });
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}

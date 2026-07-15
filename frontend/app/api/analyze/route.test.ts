// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "./route";

function post(body: unknown, headers: Record<string, string> = {}) {
  return new NextRequest("http://frontend.test/api/analyze", {
    method: "POST",
    body: JSON.stringify(body),
    headers,
  });
}

function stubBackend(status = 200, payload: unknown = { briefing: "ok" }) {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify(payload), { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("POST /api/analyze proxy", () => {
  it("returns 500 when BACKEND_URL is not configured", async () => {
    vi.stubEnv("BACKEND_URL", "");
    const res = await POST(post({ question: "q", detector: "auto" }));
    expect(res.status).toBe(500);
    expect(await res.json()).toEqual({ error: "BACKEND_URL is not configured" });
  });

  it("forwards the body to the backend and attaches the server-side API key", async () => {
    vi.stubEnv("BACKEND_URL", "http://backend.test");
    vi.stubEnv("BACKEND_API_KEY", "sekret");
    const fetchMock = stubBackend();

    const body = { question: "health check", detector: "baseline" };
    await POST(post(body));

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://backend.test/api/analyze");
    expect(init.method).toBe("POST");
    expect(init.headers["X-API-Key"]).toBe("sekret");
    expect(init.body).toBe(JSON.stringify(body));
  });

  it("omits X-API-Key when no key is configured", async () => {
    vi.stubEnv("BACKEND_URL", "http://backend.test");
    vi.stubEnv("BACKEND_API_KEY", "");
    const fetchMock = stubBackend();

    await POST(post({ question: "q", detector: "auto" }));

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers).not.toHaveProperty("X-API-Key");
  });

  it("forwards the first x-forwarded-for entry as the real client IP", async () => {
    vi.stubEnv("BACKEND_URL", "http://backend.test");
    const fetchMock = stubBackend();

    await POST(
      post(
        { question: "q", detector: "auto" },
        { "x-forwarded-for": " 203.0.113.7 , 10.0.0.1, 172.16.0.1" },
      ),
    );

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers["X-Real-Client-IP"]).toBe("203.0.113.7");
  });

  it("omits X-Real-Client-IP when there is no x-forwarded-for header", async () => {
    vi.stubEnv("BACKEND_URL", "http://backend.test");
    const fetchMock = stubBackend();

    await POST(post({ question: "q", detector: "auto" }));

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers).not.toHaveProperty("X-Real-Client-IP");
  });

  it("passes the backend status and body through unchanged", async () => {
    vi.stubEnv("BACKEND_URL", "http://backend.test");
    stubBackend(429, { detail: "search quota exceeded for this IP" });

    const res = await POST(post({ question: "q", detector: "auto" }));

    expect(res.status).toBe(429);
    expect(res.headers.get("Content-Type")).toBe("application/json");
    expect(await res.json()).toEqual({ detail: "search quota exceeded for this IP" });
  });
});

// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { analyze } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("analyze", () => {
  it("posts the question and detector to the same-origin proxy", async () => {
    const payload = { question: "q", briefing: "all good" };
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const res = await analyze("q", "omnianomaly");

    expect(res).toEqual(payload);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/analyze");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ question: "q", detector: "omnianomaly" });
  });

  it("defaults the detector to auto", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await analyze("q");

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body).detector).toBe("auto");
  });

  it("throws with status and response detail on a non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("quota exceeded", { status: 429 })),
    );

    await expect(analyze("q")).rejects.toThrow("Request failed (429): quota exceeded");
  });
});

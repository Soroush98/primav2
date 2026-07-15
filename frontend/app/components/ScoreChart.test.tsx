import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ScoreChart from "./ScoreChart";
import type { Detection, ScorePoint } from "../lib/api";

// Plot-area bounds from the component's fixed geometry (H=240, PAD=34).
const TOP = 34;
const BOTTOM = 206;

function det(points: ScorePoint[], overrides: Partial<Detection> = {}): Detection {
  return { n: points.length, points, ...overrides };
}

function circleYs(container: HTMLElement): number[] {
  return [...container.querySelectorAll("circle")].map((c) => Number(c.getAttribute("cy")));
}

describe("ScoreChart", () => {
  it("renders nothing when there are no points", () => {
    const { container } = render(<ScoreChart det={det([])} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders one circle per point, with flagged points as red dots", () => {
    const points = [
      { i: 0, score: 1.0, flag: false },
      { i: 1, score: 2.0, flag: false },
      { i: 2, score: 8.0, flag: true },
    ];
    const { container } = render(
      <ScoreChart det={det(points, { threshold: 4.0, score_max: 8.0 })} />,
    );

    expect(container.querySelectorAll("circle")).toHaveLength(3);
    expect(container.querySelectorAll('circle[fill="var(--bad)"]')).toHaveLength(1);
    expect(screen.getByText("POT threshold 4.00")).toBeInTheDocument();
  });

  it("omits the threshold line when no threshold is set", () => {
    const points = [{ i: 0, score: 1.0, flag: false }];
    render(<ScoreChart det={det(points)} />);
    expect(screen.queryByText(/POT threshold/)).not.toBeInTheDocument();
  });

  it("keeps negative scores inside the plot area (OmniAnomaly log-prob scores)", () => {
    const points = [
      { i: 0, score: -6.0, flag: false },
      { i: 1, score: -2.0, flag: false },
      { i: 2, score: 3.0, flag: true },
    ];
    const { container } = render(
      <ScoreChart det={det(points, { threshold: 1.0, score_max: 3.0 })} />,
    );

    const ys = circleYs(container);
    for (const y of ys) {
      expect(Number.isFinite(y)).toBe(true);
      expect(y).toBeGreaterThanOrEqual(TOP);
      expect(y).toBeLessThanOrEqual(BOTTOM);
    }
    // The y-domain spans the actual data: min score sits on the x-axis, max at the top.
    expect(Math.max(...ys)).toBeCloseTo(BOTTOM);
    expect(Math.min(...ys)).toBeCloseTo(TOP);
  });
});

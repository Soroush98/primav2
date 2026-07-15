import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import ForecastChart from "./ForecastChart";
import type { Detection, FeatureForecast } from "../lib/api";

function series(n: number, base: number): number[] {
  return Array.from({ length: n }, (_, i) => base + Math.sin(i / 4));
}

function feature(base: number): FeatureForecast {
  return {
    history: series(72, base),
    median: series(48, base + 2),
    lo: series(48, base - 4),
    hi: series(48, base + 8),
  };
}

function det(features: Record<string, FeatureForecast>): Detection {
  return {
    n: 2400,
    detector: "chronos",
    machine: "m_1043",
    horizon_hours: 48,
    forecast: { machine: "m_1043", horizon_hours: 48, features },
  };
}

describe("ForecastChart", () => {
  it("renders nothing without a forecast", () => {
    const { container } = render(<ForecastChart det={{ n: 0 }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the forecast has no features", () => {
    const { container } = render(<ForecastChart det={det({})} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("defaults to the cpu feature and renders the band, legend and horizon", () => {
    render(<ForecastChart det={det({ cpu: feature(40), mem: feature(60) })} />);

    expect(screen.getByText("cpu · m_1043")).toBeInTheDocument();
    expect(screen.getByText("72h of history → next 2 days (hourly)")).toBeInTheDocument();
    expect(screen.getByText("forecast median")).toBeInTheDocument();
    expect(screen.getByText("q10–q90 band")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "cpu" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "mem" })).toBeInTheDocument();
  });

  it("falls back to the first feature when cpu is absent", () => {
    render(<ForecastChart det={det({ net_in: feature(10) })} />);
    expect(screen.getByText("net_in · m_1043")).toBeInTheDocument();
  });

  it("switches the plotted feature when a chip is clicked", async () => {
    const user = userEvent.setup();
    render(<ForecastChart det={det({ cpu: feature(40), mem: feature(60) })} />);

    await user.click(screen.getByRole("button", { name: "mem" }));

    expect(screen.getByText("mem · m_1043")).toBeInTheDocument();
    expect(screen.queryByText("cpu · m_1043")).not.toBeInTheDocument();
  });
});

"""End-to-end agent-graph test with mocked LLM + BigQuery — no GCP, no data."""

import numpy as np

from app.agent.bigquery_tool import assert_read_only
from app.agent.graph import build_graph
from app.agent.nodes import AgentNodes


class FakeLLM:
    """Returns canned responses in call order: orchestrator, sql_analyst, narrator."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.i = 0

    async def generate(self, prompt, *, system=None, temperature=0.2):
        r = self.responses[min(self.i, len(self.responses) - 1)]
        self.i += 1
        return r


class FakeRunner:
    def __init__(self, rows):
        self.rows = rows

    def run_query(self, sql):
        assert_read_only(sql)  # the guard must still pass
        return self.rows


def _rows():
    rng = np.random.default_rng(0)
    rows = []
    for i in range(120):
        anom = i >= 110  # last 10 are attacks
        rows.append(
            {
                "src_addr": f"10.0.0.{i % 5}",
                "flow_count": int(rng.integers(1, 20)) + (500 if anom else 0),
                "unique_dst_ports": int(rng.integers(1, 5)) + (300 if anom else 0),
                "total_bytes": float(rng.normal(1000, 100)) + (50_000 if anom else 0),
                "label": 1 if anom else 0,
            }
        )
    return rows


async def test_agent_graph_end_to_end_with_mocks():
    llm = FakeLLM(['{"focus": "port scan"}', "SELECT * FROM `t`", "Final briefing."])
    nodes = AgentNodes(llm=llm, runner=FakeRunner(_rows()), schema_ddl="(test schema)")
    graph = build_graph(nodes)

    result = await graph.ainvoke({"question": "any port scans today?"})

    assert result["briefing"] == "Final briefing."
    assert result["sql"] == "SELECT * FROM `t`"
    assert result["detection"]["n"] == 120
    assert result["detection"]["grade"] is not None      # graded against label
    assert result["detection"]["grade"]["raw_best_f1"] > 0.5
    assert result["root_cause"]["ranked_features"]       # ranked deviating features


async def test_sql_guard_rejects_writes():
    import pytest

    for bad in ["DELETE FROM t", "DROP TABLE t", "UPDATE t SET x=1"]:
        with pytest.raises(ValueError):
            assert_read_only(bad)


# ----------------------------------------------------------- OmniAnomaly routing


class FakeOmni:
    """Duck-typed stand-in for a loaded OmniAnomalyDetector (no torch in tests)."""

    window = 3
    threshold_ = 0.5

    def score(self, seq):
        s = np.full(len(seq), 0.1)
        s[-1] = 1.0  # flag the last bin of each machine's series
        return s


def _series_rows(n_machines=2, bins_per=5):
    rng = np.random.default_rng(1)
    feats = ["cpu", "mem", "net_in", "net_out", "disk_io"]
    rows = []
    for m in range(n_machines):
        for b in range(bins_per):
            rows.append(
                {"machine_id": f"m_{m}", "bin": b, **{f: float(rng.normal(50, 5)) for f in feats}}
            )
    return rows


def _nodes(omni):
    return AgentNodes(llm=FakeLLM(["x"]), runner=FakeRunner([]), omni=omni)


def test_route_and_score_omni_on_series():
    n = _nodes(FakeOmni())
    series = _series_rows(2, 5)  # 5 bins each >= window 3
    assert n.route_detector({"rows": series, "detector": "auto"}) == "detector_omni"
    out = n.detector_omni({"rows": series})
    assert out["detection"]["detector"] == "omnianomaly"
    assert out["detection"]["n"] == 10


def test_route_to_baseline_on_snapshot():
    n = _nodes(FakeOmni())
    snap = _series_rows(8, 1)  # 1 bin each < window
    assert n.route_detector({"rows": snap, "detector": "auto"}) == "detector_baseline"


def test_mode_baseline_forces_baseline_even_on_series():
    n = _nodes(FakeOmni())
    series = _series_rows(2, 5)
    assert n.route_detector({"rows": series, "detector": "baseline"}) == "detector_baseline"


def test_mode_omni_falls_back_with_note_on_snapshot():
    out = _nodes(FakeOmni()).detector_omni({"rows": _series_rows(8, 1)})  # snapshot
    assert out["detection"]["detector"] == "baseline"
    assert "note" in out["detection"]  # explains the fallback


def test_route_baseline_when_no_model():
    n = _nodes(None)
    assert n.route_detector({"rows": _series_rows(2, 5), "detector": "auto"}) == "detector_baseline"


# -------------------------------------------------------- Chronos forecast arm


class FakeForecaster:
    """Duck-typed stand-in for a loaded ChronosForecaster (no model download in tests)."""

    window = 3

    def score(self, seq):
        s = np.full(len(seq), 0.1)
        s[-1] = 5.0  # large forecast residual on the last bin
        return s


def _fc_nodes():
    return AgentNodes(llm=FakeLLM(["x"]), runner=FakeRunner([]), forecaster=FakeForecaster())


def test_route_forecast_mode_to_forecast_arm():
    n = _fc_nodes()
    assert n.route_detector({"rows": _series_rows(2, 5), "detector": "forecast"}) == "detector_forecast"


def test_detector_forecast_scores_series():
    out = _fc_nodes().detector_forecast({"rows": _series_rows(2, 5)})
    assert out["detection"]["detector"] == "chronos"
    assert out["detection"]["n"] == 10


def test_forecast_falls_back_to_baseline_without_model():
    n = AgentNodes(llm=FakeLLM(["x"]), runner=FakeRunner([]), forecaster=None)
    out = n.detector_forecast({"rows": _series_rows(2, 5)})
    assert out["detection"]["detector"] == "baseline"
    assert "note" in out["detection"]

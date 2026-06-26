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

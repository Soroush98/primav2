from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import AgentNodes
from app.agent.state import PrimaState


def build_graph(nodes: AgentNodes):
    """Wire the Prima fleet and compile it.

    Linear except for the detector step, which is a CONDITIONAL ROUTE: after
    sql_analyst, ``route_detector`` picks an arm (baseline vs OmniAnomaly, by mode +
    data shape) and both arms converge back into root_cause. A 3rd arm (e.g. a
    Chronos-Bolt forecaster) drops in here as one more node + route key."""
    builder = StateGraph(PrimaState)
    builder.add_node("orchestrator", nodes.orchestrator)
    builder.add_node("sql_analyst", nodes.sql_analyst)
    builder.add_node("detector_baseline", nodes.detector_baseline)
    builder.add_node("detector_omni", nodes.detector_omni)
    builder.add_node("root_cause", nodes.root_cause)
    builder.add_node("narrator", nodes.narrator)

    builder.add_edge(START, "orchestrator")
    builder.add_edge("orchestrator", "sql_analyst")
    builder.add_conditional_edges(
        "sql_analyst",
        nodes.route_detector,
        {
            "detector_baseline": "detector_baseline",
            "detector_omni": "detector_omni",
            # "detector_forecast": "detector_forecast",  # ← 3rd arm slots in here
        },
    )
    builder.add_edge("detector_baseline", "root_cause")
    builder.add_edge("detector_omni", "root_cause")
    builder.add_edge("root_cause", "narrator")
    builder.add_edge("narrator", END)
    return builder.compile()

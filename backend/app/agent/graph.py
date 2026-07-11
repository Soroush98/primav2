from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import AgentNodes
from app.agent.state import PrimaState


def build_graph(nodes: AgentNodes):
    """Wire the Prima fleet and compile it.

    Linear except for the detector step, which is a CONDITIONAL ROUTE: after
    sql_analyst, ``route_detector`` picks an arm. The two anomaly arms (baseline,
    OmniAnomaly) converge into root_cause; the Chronos forecast arm does no anomaly
    detection, so it skips root_cause and goes straight to the narrator."""
    builder = StateGraph(PrimaState)
    builder.add_node("orchestrator", nodes.orchestrator)
    builder.add_node("sql_analyst", nodes.sql_analyst)
    builder.add_node("detector_baseline", nodes.detector_baseline)
    builder.add_node("detector_omni", nodes.detector_omni)
    builder.add_node("detector_forecast", nodes.detector_forecast)
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
            "detector_forecast": "detector_forecast",
        },
    )
    builder.add_edge("detector_baseline", "root_cause")
    builder.add_edge("detector_omni", "root_cause")
    # Forecast-only runs skip root_cause (nothing was flagged); when the arm fell
    # back to the baseline it produced anomaly scores, so root_cause still applies.
    builder.add_conditional_edges(
        "detector_forecast",
        lambda s: "narrator" if "forecast" in (s.get("detection") or {}) else "root_cause",
        {"narrator": "narrator", "root_cause": "root_cause"},
    )
    builder.add_edge("root_cause", "narrator")
    builder.add_edge("narrator", END)
    return builder.compile()

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import AgentNodes
from app.agent.state import PrimaState


def build_graph(nodes: AgentNodes):
    """Wire the five nodes into the linear Prima fleet and compile it."""
    builder = StateGraph(PrimaState)
    builder.add_node("orchestrator", nodes.orchestrator)
    builder.add_node("sql_analyst", nodes.sql_analyst)
    builder.add_node("detector", nodes.detector)
    builder.add_node("root_cause", nodes.root_cause)
    builder.add_node("narrator", nodes.narrator)

    builder.add_edge(START, "orchestrator")
    builder.add_edge("orchestrator", "sql_analyst")
    builder.add_edge("sql_analyst", "detector")
    builder.add_edge("detector", "root_cause")
    builder.add_edge("root_cause", "narrator")
    builder.add_edge("narrator", END)
    return builder.compile()

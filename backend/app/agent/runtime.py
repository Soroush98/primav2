from functools import lru_cache

from app.agent.graph import build_graph
from app.agent.nodes import SCHEMA_HINT, AgentNodes
from app.config import get_settings


@lru_cache
def get_agent():
    """Build the compiled agent graph once, wired with real dependencies
    (Gemini provider + BigQuery). Overridden in tests via dependency_overrides."""
    from app.agent.bigquery_tool import BigQueryRunner
    from app.llm.gemini import _provider

    settings = get_settings()
    nodes = AgentNodes(
        llm=_provider(),
        runner=BigQueryRunner(
            settings.google_cloud_project,
            max_bytes_billed=settings.bigquery_max_bytes_billed,
            max_rows=settings.bigquery_max_rows,
        ),
        schema_ddl=SCHEMA_HINT,
    )
    return build_graph(nodes)

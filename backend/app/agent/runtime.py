from functools import lru_cache

from app.agent.graph import build_graph
from app.agent.nodes import SCHEMA_HINT, AgentNodes
from app.config import get_settings


@lru_cache
def get_agent():
    """Build the compiled agent graph once, wired with real dependencies
    (Gemini provider + BigQuery). Overridden in tests via dependency_overrides."""
    from app.agent.bigquery_tool import BigQueryRunner
    from app.detectors.model_store import load_chronos, load_omni
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
        omni=load_omni(settings.omni_checkpoint_uri),    # None unless a checkpoint is set
        forecaster=load_chronos(settings.chronos_model),  # None unless a model id is set
    )
    return build_graph(nodes)

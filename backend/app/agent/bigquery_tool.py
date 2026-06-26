"""Read-only BigQuery access for the SQL Analyst node.

This module is the security boundary between an LLM that *authors* SQL and a cloud
data warehouse that *executes* it. Defence in depth:

  1. `assert_read_only`  — only SELECT/WITH; any write/DDL keyword is rejected.
  2. `assert_tables_in_project` — every fully-qualified table reference must live in
     the configured project, so a prompt-injected query cannot read other projects'
     data the credentials happen to have access to.
  3. `maximum_bytes_billed` cap + job timeout — bounds cost/latency so a crafted
     full-table scan cannot run up the bill or hang the request (cost-DoS).
  4. `max_results` row cap — bounds how many rows are materialized client-side, so
     a query that returns hundreds of thousands of rows cannot OOM the container.
"""

from __future__ import annotations

import re
from typing import Protocol

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|create|alter|merge|truncate|grant|revoke|"
    r"call|export|load|begin|commit)\b",
    re.IGNORECASE,
)
# Fully-qualified `project.dataset.table` references (backticks optional).
_TABLE_REF = re.compile(r"`?([A-Za-z0-9_-]+)`?\.`?([A-Za-z0-9_-]+)`?\.`?([A-Za-z0-9_-]+)`?")


def assert_read_only(sql: str) -> None:
    stripped = sql.strip().rstrip(";").strip()
    if not re.match(r"(?is)^\s*(select|with)\b", stripped):
        raise ValueError("only SELECT/WITH queries are allowed")
    if _FORBIDDEN.search(stripped):
        raise ValueError("query contains a forbidden write/DDL keyword")
    if ";" in stripped:
        raise ValueError("multiple statements are not allowed")


def assert_tables_in_project(sql: str, project: str) -> None:
    """Reject any 3-part table reference whose project is not ``project``."""
    for m in _TABLE_REF.finditer(sql):
        if m.group(1) != project:
            raise ValueError(f"query references a table outside project '{project}'")


class QueryRunner(Protocol):
    def run_query(self, sql: str) -> list[dict]: ...


class BigQueryRunner:
    def __init__(
        self,
        project: str,
        *,
        max_bytes_billed: int = 50_000_000_000,  # ~50 GB — bounds cost-DoS
        max_rows: int = 50_000,  # rows materialized client-side — bounds memory (OOM)
        job_timeout: float = 60.0,
    ) -> None:
        from google.cloud import bigquery  # lazy: avoids client construction at import

        self._bigquery = bigquery
        self._project = project
        self._client = bigquery.Client(project=project)
        self._max_bytes = max_bytes_billed
        self._max_rows = max_rows
        self._timeout = job_timeout

    def run_query(self, sql: str) -> list[dict]:
        assert_read_only(sql)
        assert_tables_in_project(sql, self._project)
        config = self._bigquery.QueryJobConfig(
            maximum_bytes_billed=self._max_bytes,
            use_query_cache=True,
        )
        job = self._client.query(sql, job_config=config, timeout=self._timeout)
        # max_results bounds the rows downloaded into memory regardless of how many
        # the (LLM-authored) query would return — the OOM guard.
        rows = job.result(timeout=self._timeout, max_results=self._max_rows)
        return [dict(row) for row in rows]

"""The five agent nodes, parameterized by their dependencies (LLM, BigQuery
runner, schema) so they can be unit-tested with fakes — no network, no GCP."""

from __future__ import annotations

import json
import re

import numpy as np

from app.agent.bigquery_tool import QueryRunner, assert_read_only
from app.detectors.baseline import BaselineDetector
from app.eval.metrics import evaluate

# Real schema, introspected from the loaded tables (see warehouse/alibaba_windowing.sql).
SCHEMA_HINT = """BigQuery dataset `primav2.alibaba_cluster` (Alibaba cluster-trace-v2018,
per-machine resource telemetry over time). Read-only: emit a single SELECT/WITH query.
`time_stamp` / `bin` give a REAL time axis (seconds / 5-min index from t0).

Table `machine_usage` — 246,934,820 raw samples (one machine per ~10–100s). Huge:
always aggregate or LIMIT. Columns:
  machine_id STRING, time_stamp INT64 (seconds from start),
  cpu_util_percent INT64 [0,100], mem_util_percent INT64 [0,100],
  mem_gps FLOAT64 (mem bandwidth; ~79% NULL), mkpi FLOAT64 (cache miss/1k instr; ~79% NULL),
  net_in FLOAT64 [0,100], net_out FLOAT64 [0,100],
  disk_io_percent FLOAT64 [0,100] (abnormal markers: -1 or 101).

Table `usage_5min` — 8,389,672 rows: telemetry resampled to regular 5-min bins per
machine (the detector's unit; ORDER BY bin = chronological order). Columns:
  machine_id STRING, bin INT64 (5-min timestep index),
  cpu FLOAT64, mem FLOAT64, net_in FLOAT64, net_out FLOAT64, disk_io FLOAT64 (bin means),
  n_disk_abnormal INT64 (count of -1/101 disk_io in the bin), n_samples INT64.

Table `machine_meta` — machine status snapshots: machine_id STRING, time_stamp INT64,
  failure_domain_1 INT64, failure_domain_2 STRING, cpu_num INT64, mem_size INT64,
  status STRING (almost all 'USING')."""

_MAD_SCALE = 0.6744897501960817

# Feature order the OmniAnomaly checkpoint was trained on — must match
# app.eval.alibaba.FEATURES (the checkpoint stores mean/std, not column names).
OMNI_FEATURES = ["cpu", "mem", "net_in", "net_out", "disk_io"]


def _safe_json(text: str) -> dict:
    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        return json.loads(match.group(0)) if match else {"raw": text.strip()}
    except (ValueError, json.JSONDecodeError):
        return {"raw": text.strip()}


def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t)
    return t.strip()


def _window_label(row: dict, i: int, score: float) -> dict:
    """Identify an anomalous window by machine/bin when present, else by row index."""
    if "machine_id" in row:
        label = str(row["machine_id"])
        if row.get("bin") is not None:
            label += f" · bin {row['bin']}"
    else:
        sid = next((str(v) for v in row.values() if isinstance(v, str)), None)
        label = sid or f"row {i}"
    return {"i": i, "label": label, "score": round(score, 3)}


def _downsample_points(scores: np.ndarray, flag: np.ndarray, cap: int = 400) -> list[dict]:
    """Scored series for the UI scatter: keep the highest-scoring flagged windows
    (the dots) plus a uniform sample of the rest, capped to ``cap`` points."""
    idx = np.arange(len(scores))
    fl, nf = idx[flag], idx[~flag]
    if len(fl) > cap // 2:
        fl = fl[np.argsort(scores[fl])[::-1][: cap // 2]]
    room = cap - len(fl)
    if room > 0 and len(nf) > room:
        nf = nf[np.linspace(0, len(nf) - 1, room).astype(int)]
    keep = np.sort(np.concatenate([fl, nf])) if room > 0 else np.sort(fl)
    return [
        {"i": int(i), "score": round(float(scores[i]), 4), "flag": bool(flag[i])}
        for i in keep
    ]


def _numeric_matrix(rows: list[dict]) -> tuple[list[str], np.ndarray]:
    _non_features = {"label", "window_id", "bin"}  # targets / time indices, not detector inputs
    cols = [
        k
        for k, v in rows[0].items()
        if isinstance(v, (int, float)) and not isinstance(v, bool) and k not in _non_features
    ]
    X = np.array([[float(r.get(c) or 0.0) for c in cols] for r in rows], dtype=float)
    return cols, X


class AgentNodes:
    def __init__(
        self,
        llm,
        runner: QueryRunner,
        schema_ddl: str = SCHEMA_HINT,
        detector_factory=BaselineDetector,
        omni=None,                       # pretrained OmniAnomaly detector, or None
        omni_features=OMNI_FEATURES,
    ) -> None:
        self.llm = llm
        self.runner = runner
        self.schema = schema_ddl
        self.detector_factory = detector_factory
        self.omni = omni
        self.omni_features = list(omni_features)

    async def orchestrator(self, state: dict) -> dict:
        text = await self.llm.generate(
            f"User question: {state['question']}\n\n"
            "Extract the analysis intent as compact JSON with keys "
            '"focus" (what to look for) and "entities" (machine ids, metrics, time ranges).',
            system="You parse machine-reliability / time-series questions into structured intent. JSON only.",
        )
        return {"focus": _safe_json(text)}

    async def sql_analyst(self, state: dict) -> dict:
        sql = _strip_code_fence(
            await self.llm.generate(
                f"Schema:\n{self.schema}\n\n"
                f"Question: {state['question']}\nIntent: {state.get('focus')}\n\n"
                "Write ONE read-only BigQuery SQL (SELECT/WITH only) returning per-machine/per-bin "
                "numeric metrics plus machine_id (and bin for time order). "
                "Scope tightly: prefer `usage_5min`; default to the LATEST bin only "
                "(one row per machine, ~4k rows) unless the question explicitly asks for a time "
                "range — then bound it to a small recent window. ALWAYS end with an explicit "
                "`LIMIT 50000` as a backstop. Reply with SQL only.",
                system="You author safe, read-only BigQuery SQL. SELECT/WITH only.",
            )
        )
        try:
            assert_read_only(sql)
            rows = self.runner.run_query(sql)
        except Exception as exc:  # surfaced to the narrator, never crashes the graph
            return {"sql": sql, "rows": [], "error": f"sql_analyst: {exc}"}
        return {"sql": sql, "rows": rows}

    def detector(self, state: dict) -> dict:
        rows = state.get("rows") or []
        if not rows:
            return {"detection": {"n": 0, "flagged": 0, "note": "no rows returned"}}
        cols, X = _numeric_matrix(rows)
        if not cols:
            return {"detection": {"n": len(rows), "flagged": 0, "note": "no numeric features"}}

        # OmniAnomaly serves when the data is a per-machine time series it can window;
        # otherwise (e.g. a latest-bin snapshot) fall back to the MAD/EVT baseline.
        omni = self._omni_detect(rows)
        if omni is not None:
            scores, thr, used = omni
        else:
            det = self.detector_factory().fit(X)
            scores = np.nan_to_num(det.score(X), posinf=0.0, neginf=0.0)
            thr = float(det.threshold_) if det.threshold_ is not None else float(scores.max())
            used = "baseline"
        flag = scores >= thr
        grade = None
        if "label" in rows[0]:
            y = np.array([int(r.get("label") or 0) for r in rows])
            if 0 < int(y.sum()) < len(y):
                grade = evaluate(y, scores).as_dict()
        order = np.argsort(scores)[::-1]
        return {
            "feature_cols": cols,
            "detection": {
                "n": len(rows),
                "flagged": int(flag.sum()),
                "threshold": thr,
                "score_max": float(scores.max()),
                "detector": used,
                "top_windows": [_window_label(rows[int(i)], int(i), float(scores[i])) for i in order[:8]],
                "points": _downsample_points(scores, flag, cap=400),  # for the UI scatter
                "grade": grade,
            },
        }

    def _omni_detect(self, rows: list[dict]):
        """OmniAnomaly scoring for per-machine time series. Returns
        ``(scores aligned to rows, threshold, "omnianomaly")`` when it applies, else
        ``None`` to fall back to the baseline.

        Applies only when a pretrained model is loaded, the rows carry the trained
        features + ``machine_id``, and at least one machine has ``>= window`` bins (so
        the model has a real temporal window to score — a snapshot has none)."""
        if self.omni is None:
            return None
        feats = self.omni_features
        r0 = rows[0]
        if "machine_id" not in r0 or any(f not in r0 for f in feats):
            return None
        window = self.omni.window
        groups: dict = {}
        for i, r in enumerate(rows):
            groups.setdefault(r["machine_id"], []).append(i)
        scores = np.zeros(len(rows), dtype=float)
        scored = 0
        for idxs in groups.values():
            if "bin" in r0:  # ensure chronological order within the machine
                idxs = sorted(idxs, key=lambda i: rows[i].get("bin") or 0)
            if len(idxs) < window:
                continue
            seq = np.array(
                [[float(rows[i].get(f) or 0.0) for f in feats] for i in idxs], dtype=float
            )
            s = np.nan_to_num(self.omni.score(seq), posinf=0.0, neginf=0.0)
            for k, i in enumerate(idxs):
                scores[i] = float(s[k])
            scored += len(idxs)
        if scored == 0:  # no machine had a long enough series — let the baseline handle it
            return None
        thr = (
            float(self.omni.threshold_)
            if self.omni.threshold_ is not None
            else float(scores.max())
        )
        return scores, thr, "omnianomaly"

    def root_cause(self, state: dict) -> dict:
        rows = state.get("rows") or []
        cols = state.get("feature_cols") or []
        if not rows or not cols:
            return {"root_cause": {}}
        X = np.array([[float(r.get(c) or 0.0) for c in cols] for r in rows], dtype=float)
        median = np.median(X, axis=0)
        mad = np.median(np.abs(X - median), axis=0)
        mad = np.where(mad == 0, 1e-9, mad)
        z = _MAD_SCALE * np.abs(X - median) / mad
        top_raw = state.get("detection", {}).get("top_windows") or []
        top = [w["i"] if isinstance(w, dict) else int(w) for w in top_raw] or list(
            range(min(5, len(rows)))
        )
        deviation = z[top].mean(axis=0)
        ranked = sorted(
            zip(cols, deviation.tolist(), strict=True), key=lambda kv: kv[1], reverse=True
        )[:5]
        return {"root_cause": {"ranked_features": ranked}}

    async def narrator(self, state: dict) -> dict:
        det = {k: v for k, v in (state.get("detection") or {}).items() if k != "points"}
        briefing = await self.llm.generate(
            f"Question: {state['question']}\n"
            f"Detection: {det}\n"
            f"Root cause (top deviating features): {state.get('root_cause')}\n"
            f"Error: {state.get('error')}\n\n"
            "Write a concise (3-5 sentence) reliability briefing grounded in these numbers. "
            "When citing anomalies, name the machine/bin from top_windows rather than row indices.",
            system="You are Prima, a machine-reliability analyst. Be concise and evidence-led.",
        )
        return {"briefing": briefing}

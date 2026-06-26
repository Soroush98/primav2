"""The five agent nodes, parameterized by their dependencies (LLM, BigQuery
runner, schema) so they can be unit-tested with fakes — no network, no GCP."""

from __future__ import annotations

import json
import re

import numpy as np

from app.agent.bigquery_tool import QueryRunner, assert_read_only
from app.detectors.baseline import BaselineDetector, pot_threshold
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


def _prep(rows: list[dict]):
    """Return ``(cols, X)`` to score, or ``(None, None)`` if there's nothing numeric."""
    if not rows:
        return None, None
    cols, X = _numeric_matrix(rows)
    return (cols, X) if cols else (None, None)


def _empty_detection(rows: list[dict]) -> dict:
    note = "no rows returned" if not rows else "no numeric features"
    return {"detection": {"n": len(rows), "flagged": 0, "note": note}}


class AgentNodes:
    def __init__(
        self,
        llm,
        runner: QueryRunner,
        schema_ddl: str = SCHEMA_HINT,
        detector_factory=BaselineDetector,
        omni=None,                       # pretrained OmniAnomaly detector, or None
        forecaster=None,                 # Chronos-Bolt forecaster, or None
        omni_features=OMNI_FEATURES,
    ) -> None:
        self.llm = llm
        self.runner = runner
        self.schema = schema_ddl
        self.detector_factory = detector_factory
        self.omni = omni
        self.forecaster = forecaster
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
        # The requested detector mode steers the QUERY SHAPE: OmniAnomaly and Chronos
        # need a per-machine time series; the baseline works on a latest-bin snapshot.
        if state.get("detector") in ("omnianomaly", "forecast"):
            guidance = (
                "TEMPORAL mode (for OmniAnomaly / Chronos): return ONE machine's full per-bin "
                "series from `usage_5min` (machine_id, bin, cpu, mem, net_in, net_out, disk_io) "
                "ORDERED BY bin — at least ~200 consecutive bins. NEVER hardcode a machine_id; "
                "pick one from the data (e.g. the machine_id with the most rows)."
            )
        else:
            guidance = (
                "Prefer `usage_5min`; default to the LATEST bin only (one row per machine, ~4k "
                "rows) unless the question explicitly asks for a time range — then bound it to a "
                "small recent window. If you filter to one machine, SELECT it from the data — "
                "never hardcode an id."
            )
        sql = _strip_code_fence(
            await self.llm.generate(
                f"Schema:\n{self.schema}\n\n"
                f"Question: {state['question']}\nIntent: {state.get('focus')}\n\n"
                "Write ONE read-only BigQuery SQL (SELECT/WITH only) returning per-machine/per-bin "
                f"numeric metrics plus machine_id (and bin for time order). {guidance} "
                "ALWAYS end with an explicit `LIMIT 50000` as a backstop. Reply with SQL only.",
                system="You author safe, read-only BigQuery SQL. SELECT/WITH only.",
            )
        )
        try:
            assert_read_only(sql)
            rows = self.runner.run_query(sql)
        except Exception as exc:  # surfaced to the narrator, never crashes the graph
            return {"sql": sql, "rows": [], "error": f"sql_analyst: {exc}"}
        return {"sql": sql, "rows": rows}

    # ---- detector arms, picked by `route_detector` (a LangGraph conditional edge) ----
    # Two arms today (baseline, omnianomaly); a 3rd (e.g. a Chronos-Bolt forecaster)
    # drops in as another `detector_*` node + a `route_detector` branch + a graph entry.

    def route_detector(self, state: dict) -> str:
        """Conditional-edge router: choose the detector arm for this request.

        ``baseline``/``omnianomaly`` force an arm; ``auto`` (default) sends per-machine
        time series to OmniAnomaly and latest-bin snapshots to the baseline."""
        mode = state.get("detector", "auto")
        if mode == "baseline":
            return "detector_baseline"
        if mode == "omnianomaly":
            return "detector_omni"
        if mode == "forecast":
            return "detector_forecast"
        rows = state.get("rows") or []
        if self.omni is not None and self._is_series(rows):
            return "detector_omni"
        return "detector_baseline"

    def detector_baseline(self, state: dict) -> dict:
        """MAD/EVT baseline arm — order-invariant, scores any numeric matrix."""
        rows = state.get("rows") or []
        cols, X = _prep(rows)
        if cols is None:
            return _empty_detection(rows)
        scores, thr = self._baseline_scores(X)
        return self._assemble(rows, cols, scores, thr, "baseline")

    def detector_omni(self, state: dict) -> dict:
        """OmniAnomaly arm — windows each machine's series. Falls back to the baseline
        (with a note) when no model is loaded or the data isn't a per-machine series."""
        rows = state.get("rows") or []
        cols, X = _prep(rows)
        if cols is None:
            return _empty_detection(rows)
        omni = self._omni_detect(rows)
        if omni is None:
            scores, thr = self._baseline_scores(X)
            note = "OmniAnomaly needs a per-machine time series; used baseline instead"
            return self._assemble(rows, cols, scores, thr, "baseline", note=note)
        scores, thr = omni
        return self._assemble(rows, cols, scores, thr, "omnianomaly")

    def detector_forecast(self, state: dict) -> dict:
        """Chronos-Bolt forecaster arm — flags points whose actual value falls far
        outside the model's forecast band. Falls back to the baseline (with a note)
        when the forecaster isn't enabled or the data isn't a per-machine series."""
        rows = state.get("rows") or []
        cols, X = _prep(rows)
        if cols is None:
            return _empty_detection(rows)
        fc = self._forecast_detect(rows)
        if fc is None:
            scores, thr = self._baseline_scores(X)
            note = "Chronos forecaster unavailable / needs a per-machine series; used baseline"
            return self._assemble(rows, cols, scores, thr, "baseline", note=note)
        scores, thr = fc
        return self._assemble(rows, cols, scores, thr, "chronos")

    def _baseline_scores(self, X: np.ndarray) -> tuple[np.ndarray, float]:
        det = self.detector_factory().fit(X)
        scores = np.nan_to_num(det.score(X), posinf=0.0, neginf=0.0)
        thr = float(det.threshold_) if det.threshold_ is not None else float(scores.max())
        return scores, thr

    def _assemble(self, rows, cols, scores, thr, used, note=None) -> dict:
        """Shared post-processing for every arm: flag, grade, rank, downsample."""
        flag = scores >= thr
        grade = None
        if "label" in rows[0]:
            y = np.array([int(r.get("label") or 0) for r in rows])
            if 0 < int(y.sum()) < len(y):
                grade = evaluate(y, scores).as_dict()
        order = np.argsort(scores)[::-1]
        detection = {
            "n": len(rows),
            "flagged": int(flag.sum()),
            "threshold": thr,
            "score_max": float(scores.max()),
            "detector": used,
            "top_windows": [_window_label(rows[int(i)], int(i), float(scores[i])) for i in order[:8]],
            "points": _downsample_points(scores, flag, cap=400),  # for the UI scatter
            "grade": grade,
        }
        if note:
            detection["note"] = note
        return {"feature_cols": cols, "detection": detection}

    def _is_series(self, rows: list[dict]) -> bool:
        """True if rows look like a per-machine time series the model can window."""
        if not rows or "machine_id" not in rows[0]:
            return False
        window = getattr(self.omni, "window", 100)
        counts: dict = {}
        for r in rows:
            counts[r["machine_id"]] = counts.get(r["machine_id"], 0) + 1
        return any(c >= window for c in counts.values())

    def _series_scores(self, model, rows: list[dict]):
        """Score each machine's per-bin series with ``model.score`` (a model exposing
        ``window`` + ``score(seq)``). Returns ``scores aligned to rows`` or ``None`` when
        it can't apply (no model, missing trained features, or no machine with
        ``>= window`` bins). Shared by the OmniAnomaly and Chronos arms."""
        if model is None:
            return None
        feats = self.omni_features
        r0 = rows[0]
        if "machine_id" not in r0 or any(f not in r0 for f in feats):
            return None
        groups: dict = {}
        for i, r in enumerate(rows):
            groups.setdefault(r["machine_id"], []).append(i)
        scores = np.zeros(len(rows), dtype=float)
        scored = 0
        for idxs in groups.values():
            if "bin" in r0:  # chronological order within the machine
                idxs = sorted(idxs, key=lambda i: rows[i].get("bin") or 0)
            if len(idxs) < model.window:
                continue
            seq = np.array(
                [[float(rows[i].get(f) or 0.0) for f in feats] for i in idxs], dtype=float
            )
            s = np.nan_to_num(model.score(seq), posinf=0.0, neginf=0.0)
            for k, i in enumerate(idxs):
                scores[i] = float(s[k])
            scored += len(idxs)
        return scores if scored else None

    def _omni_detect(self, rows: list[dict]):
        """OmniAnomaly per-machine scoring → ``(scores, threshold)`` or ``None``."""
        scores = self._series_scores(self.omni, rows)
        if scores is None:
            return None
        thr = (
            float(self.omni.threshold_)
            if self.omni.threshold_ is not None
            else float(scores.max())
        )
        return scores, thr

    def _forecast_detect(self, rows: list[dict]):
        """Chronos forecast-residual scoring → ``(scores, threshold)`` or ``None``.
        Threshold is POT over the combined residuals — Chronos is zero-shot, so there's
        no trained threshold to reuse."""
        scores = self._series_scores(self.forecaster, rows)
        if scores is None:
            return None
        nz = scores[scores > 0]
        if len(nz) >= 20:
            try:
                thr = float(pot_threshold(nz, 1e-3))
            except Exception:  # noqa: BLE001 — POT can be unstable on short tails
                thr = float(np.quantile(nz, 0.98))
        else:
            thr = float(nz.max()) if len(nz) else float(scores.max())
        return scores, thr

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

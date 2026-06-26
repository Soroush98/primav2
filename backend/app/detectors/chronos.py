"""Chronos-Bolt forecaster as a forecast-residual anomaly detector — the 3rd arm.

Zero-shot (no training): for each feature's univariate series, forecast each recent
point from its preceding ``context`` values and score how far the actual value falls
outside the predicted quantile band (q10..q90). Residuals are averaged across features
to a per-timestep anomaly score. Same ``window`` / ``score`` / ``threshold_`` shape as
the other arms so ``detector_forecast`` can use it interchangeably.

Cost-bounded: only the most recent ``max_score`` points of each series are scored
(forecasting every point of a long series on CPU is expensive), and all (feature,
position) contexts go through the model in a single batched ``predict`` call.
"""

from __future__ import annotations

import numpy as np

from app.detectors.baseline import pot_threshold


class ChronosForecaster:
    def __init__(
        self,
        model_name: str = "amazon/chronos-bolt-small",
        *,
        context: int = 64,
        max_score: int = 256,
        device: str = "cpu",
        q: float = 1e-3,
    ) -> None:
        import torch
        from chronos import BaseChronosPipeline

        self._torch = torch
        dtype = torch.float32 if device == "cpu" else torch.bfloat16
        self.pipe = BaseChronosPipeline.from_pretrained(
            model_name, device_map=device, torch_dtype=dtype
        )
        self.model_name = model_name
        self.context = context
        self.window = context  # min bins per machine to apply (routing parity with omni)
        self.max_score = max_score
        self.q = q
        self.threshold_: float | None = None
        # actual-vs-forecast detail of the top-residual feature, for the UI plot.
        self.last_detail: dict | None = None

    def score(self, X: np.ndarray) -> np.ndarray:
        """``X``: (T, F) per-machine series → (T,) forecast-residual anomaly score."""
        X = np.asarray(X, dtype=np.float32)
        t, f = X.shape
        scores = np.zeros(t, dtype=float)
        self.last_detail = None
        if t <= self.context:
            return scores  # too short to forecast — caller falls back

        start = max(self.context, t - self.max_score)  # score only the recent window
        positions = np.arange(start, t)

        # One batched predict over every (feature, position) context window.
        ctx = np.stack(
            [X[p - self.context : p, j] for j in range(f) for p in positions]
        )  # (F * P, context)
        q, _ = self.pipe.predict_quantiles(
            inputs=self._torch.tensor(ctx, dtype=self._torch.float32),
            prediction_length=1,
            quantile_levels=[0.1, 0.5, 0.9],
        )
        qn = q.float().cpu().numpy()[:, 0, :]  # (F*P, 3) → q10, q50, q90
        lo, med, hi = qn[:, 0], qn[:, 1], qn[:, 2]
        actual = np.concatenate([X[positions, j] for j in range(f)])
        resid = np.abs(actual - med) / np.maximum(hi - lo, 1e-6)
        p = len(positions)
        per_feat = resid.reshape(f, p)  # (F, P)
        agg = per_feat.mean(axis=0)
        scores[positions] = agg

        # Stash actual-vs-forecast for the most-deviating feature (drives the UI plot).
        top = int(per_feat.mean(axis=1).argmax())
        self.last_detail = {
            "feature": top,
            "actual": actual.reshape(f, p)[top].tolist(),
            "median": med.reshape(f, p)[top].tolist(),
            "lo": lo.reshape(f, p)[top].tolist(),
            "hi": hi.reshape(f, p)[top].tolist(),
            "score": agg.tolist(),
        }

        nz = scores[scores > 0]
        if len(nz) >= 20:
            try:
                self.threshold_ = float(pot_threshold(nz, self.q))
            except Exception:  # noqa: BLE001 — POT can be unstable on short tails
                self.threshold_ = float(np.quantile(nz, 0.98))
        else:
            self.threshold_ = float(nz.max()) if len(nz) else 1.0
        return scores

    def predict(self, X: np.ndarray) -> np.ndarray:
        s = self.score(X)
        return (s >= (self.threshold_ or s.max())).astype(int)

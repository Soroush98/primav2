"""Chronos-Bolt zero-shot forecaster — the 3rd arm.

Forecast-only (no anomaly detection): resample a machine's 5-min series to hourly
means, then forecast the next ``horizon_hours`` (default 2 days) for every feature
in one batched ``predict_quantiles`` call, returning the q10/q50/q90 band. The
hourly resample keeps the default horizon at 48 steps — inside the model's native
64-step single-shot range (at raw 5-min resolution it would be 576 steps, forcing
the pipeline's degraded autoregressive rollout).
"""

from __future__ import annotations

import numpy as np


class ChronosForecaster:
    def __init__(
        self,
        model_name: str = "amazon/chronos-bolt-small",
        *,
        horizon_hours: int = 2 * 24,
        bin_seconds: int = 300,
        min_context_hours: int = 24,
        max_context_hours: int = 512,
        device: str = "cpu",
    ) -> None:
        import torch
        from chronos import BaseChronosPipeline

        self._torch = torch
        dtype = torch.float32 if device == "cpu" else torch.bfloat16
        self.pipe = BaseChronosPipeline.from_pretrained(
            model_name, device_map=device, torch_dtype=dtype
        )
        self.model_name = model_name
        self.horizon_hours = horizon_hours
        self.bins_per_hour = max(1, 3600 // bin_seconds)
        self.min_bins = min_context_hours * self.bins_per_hour  # series check in nodes
        self.max_context_hours = max_context_hours

    def forecast(self, X: np.ndarray) -> dict | None:
        """``X``: (T, F) per-machine 5-min series → hourly history + 2-day forecast.

        Returns ``{"history": (F, Hh), "median"/"lo"/"hi": (F, horizon), "horizon_hours"}``
        (arrays as lists), or ``None`` when the series is too short — the caller
        falls back to the baseline.
        """
        X = np.asarray(X, dtype=np.float32)
        t, f = X.shape
        bph = self.bins_per_hour
        hours = t // bph
        if t < self.min_bins or hours < 2:
            return None

        # Trailing full hours → hourly means, capped to bound cost and payload size.
        tail = X[t - hours * bph :]
        hourly = tail.reshape(hours, bph, f).mean(axis=1).T  # (F, hours)
        hourly = hourly[:, -self.max_context_hours :]

        q, _ = self.pipe.predict_quantiles(
            inputs=self._torch.tensor(hourly, dtype=self._torch.float32),
            prediction_length=self.horizon_hours,
            quantile_levels=[0.1, 0.5, 0.9],
        )
        qn = q.float().cpu().numpy()  # (F, horizon, 3) → q10, q50, q90
        return {
            "history": hourly.tolist(),
            "lo": qn[:, :, 0].tolist(),
            "median": qn[:, :, 1].tolist(),
            "hi": qn[:, :, 2].tolist(),
            "horizon_hours": int(self.horizon_hours),
        }

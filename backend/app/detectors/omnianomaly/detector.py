"""OmniAnomaly detector wrapper — same fit/score/predict interface as the
baseline so the benchmark can swap them. Operates on a multivariate time series
``X`` of shape (n_timesteps, n_features): slides a length-``window`` sub-window and
scores its last point (per the paper), aligning back to per-timestep scores.
"""

from __future__ import annotations

import numpy as np
import torch
from torch.nn.utils import clip_grad_norm_

from app.detectors.baseline import pot_threshold
from app.detectors.omnianomaly.model import OmniAnomaly


class OmniAnomalyDetector:
    def __init__(
        self,
        n_features: int,
        window: int = 30,
        z_dim: int = 3,
        hidden: int = 32,
        n_flows: int = 2,
        lr: float = 1e-3,
        epochs: int = 10,
        batch: int = 64,
        mc_samples: int = 10,
        q: float = 1e-3,
        device: str = "cpu",
        seed: int = 0,
    ) -> None:
        torch.manual_seed(seed)
        self.window = window
        self.epochs = epochs
        self.batch = batch
        self.mc_samples = mc_samples
        self.q = q
        self.lr = lr
        self.seed = seed
        self.device = torch.device(device)
        self.model = OmniAnomaly(n_features, z_dim, hidden, n_flows).to(self.device)
        self.mean_: np.ndarray | None = None
        self.std_: np.ndarray | None = None
        self.threshold_: float | None = None

    def _standardize(self, X: np.ndarray) -> np.ndarray:
        return (X - self.mean_) / self.std_

    def _windows(self, X: np.ndarray) -> np.ndarray:
        n = X.shape[0]
        if n < self.window:
            raise ValueError(f"series length {n} < window {self.window}")
        idx = np.arange(self.window)[None, :] + np.arange(n - self.window + 1)[:, None]
        return X[idx]  # (n - window + 1, window, n_features)

    def _tensor(self, W: np.ndarray) -> torch.Tensor:
        return torch.tensor(W, dtype=torch.float32, device=self.device)

    def fit(self, train: np.ndarray) -> list[float]:
        torch.manual_seed(self.seed)
        train = np.asarray(train, dtype=np.float32)
        self.mean_ = train.mean(axis=0)
        self.std_ = train.std(axis=0) + 1e-6
        tensor = self._tensor(self._windows(self._standardize(train)))

        opt = torch.optim.Adam(self.model.parameters(), lr=self.lr)
        history: list[float] = []
        self.model.train()
        for _ in range(self.epochs):
            perm = torch.randperm(len(tensor), device=self.device)
            losses = []
            for i in range(0, len(tensor), self.batch):
                xb = tensor[perm[i : i + self.batch]]
                opt.zero_grad()
                loss = self.model.elbo_loss(xb)
                loss.backward()
                clip_grad_norm_(self.model.parameters(), 10.0)
                opt.step()
                losses.append(loss.item())
            history.append(float(np.mean(losses)))

        self.threshold_ = pot_threshold(self._window_scores(tensor), self.q)
        return history

    def _window_scores(self, tensor: torch.Tensor) -> np.ndarray:
        self.model.eval()
        out = []
        for i in range(0, len(tensor), self.batch):
            agg, _ = self.model.score_last(tensor[i : i + self.batch], self.mc_samples)
            out.append((-agg).cpu().numpy())  # negative recon log-prob = anomaly score
        return np.concatenate(out)

    def _align(self, X: np.ndarray, window_values: np.ndarray) -> np.ndarray:
        full = np.empty(len(X), dtype=window_values.dtype if window_values.ndim == 1 else float)
        if window_values.ndim == 1:
            full = np.empty(len(X))
            full[self.window - 1 :] = window_values
            full[: self.window - 1] = window_values[0]
            return full
        full = np.empty((len(X), window_values.shape[1]))
        full[self.window - 1 :] = window_values
        full[: self.window - 1] = window_values[0]
        return full

    def score(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=np.float32)
        tensor = self._tensor(self._windows(self._standardize(X)))
        return self._align(X, self._window_scores(tensor))

    def predict(self, X: np.ndarray) -> np.ndarray:
        assert self.threshold_ is not None, "call fit() first"
        return (self.score(X) >= self.threshold_).astype(int)

    def interpret(self, X: np.ndarray) -> np.ndarray:
        """Per-dimension anomaly contribution (negative per-dim recon log-prob),
        aligned to each timestep. Highest dims = root-cause candidates."""
        X = np.asarray(X, dtype=np.float32)
        tensor = self._tensor(self._windows(self._standardize(X)))
        self.model.eval()
        per_dim = []
        for i in range(0, len(tensor), self.batch):
            _, pd = self.model.score_last(tensor[i : i + self.batch], self.mc_samples)
            per_dim.append((-pd).cpu().numpy())
        return self._align(X, np.concatenate(per_dim))

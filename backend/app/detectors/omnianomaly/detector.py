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
        connected_q: bool = True,
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
        # Architecture knobs kept as attributes so save()/load() can reconstruct.
        self.n_features = n_features
        self.z_dim = z_dim
        self.hidden = hidden
        self.n_flows = n_flows
        self.connected_q = connected_q
        self.model = OmniAnomaly(n_features, z_dim, hidden, n_flows, connected_q).to(self.device)
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
        """Fit on a single ``(n_timesteps, n_features)`` series."""
        train = np.asarray(train, dtype=np.float32)
        self.mean_ = train.mean(axis=0)
        self.std_ = train.std(axis=0) + 1e-6
        return self._fit_tensor(self._tensor(self._windows(self._standardize(train))))

    def fit_series(self, series: list[np.ndarray]) -> list[float]:
        """Fit one GLOBAL model on many independent series (e.g. one per machine).

        Sliding windows are built WITHIN each series only — none span a machine
        boundary — while standardization and the POT threshold are pooled across the
        whole set. This is the production path: a single model that scores any
        machine, including ones it never trained on.
        """
        arrs = [np.asarray(s, dtype=np.float32) for s in series]
        if not arrs:
            raise ValueError("fit_series got no series")
        stacked = np.concatenate(arrs, axis=0)
        self.mean_ = stacked.mean(axis=0)
        self.std_ = stacked.std(axis=0) + 1e-6
        per_series = [
            self._windows(self._standardize(s)) for s in arrs if len(s) >= self.window
        ]
        if not per_series:
            raise ValueError(f"no series is at least window={self.window} long")
        return self._fit_tensor(self._tensor(np.concatenate(per_series, axis=0)))

    def _fit_tensor(self, tensor: torch.Tensor) -> list[float]:
        """Shared training loop over a (n_windows, window, n_features) tensor."""
        torch.manual_seed(self.seed)
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

    def save(self, path: str) -> None:
        """Serialize architecture + weights + standardization + threshold to a local
        file. Reconstruct a ready-to-score detector with ``OmniAnomalyDetector.load``.
        (GCS upload is the caller's job — keeps this module torch-only.)"""
        if self.mean_ is None or self.threshold_ is None:
            raise RuntimeError("fit the detector before save()")
        torch.save(
            {
                "config": {
                    "n_features": self.n_features,
                    "window": self.window,
                    "z_dim": self.z_dim,
                    "hidden": self.hidden,
                    "n_flows": self.n_flows,
                    "connected_q": self.connected_q,
                    "mc_samples": self.mc_samples,
                    "batch": self.batch,
                    "q": self.q,
                },
                "model_state": self.model.state_dict(),
                "mean": np.asarray(self.mean_, dtype=np.float32),
                "std": np.asarray(self.std_, dtype=np.float32),
                "threshold": float(self.threshold_),
            },
            path,
        )

    @classmethod
    def load(cls, path: str, device: str = "cpu") -> "OmniAnomalyDetector":
        """Load a checkpoint written by ``save`` into a detector ready for ``score``."""
        ckpt = torch.load(path, map_location=device, weights_only=False)
        c = ckpt["config"]
        det = cls(
            n_features=c["n_features"], window=c["window"], z_dim=c["z_dim"],
            hidden=c["hidden"], n_flows=c["n_flows"],
            # Checkpoints saved before the connected-posterior existed lack the key
            # and must reconstruct the old parallel-posterior architecture.
            connected_q=c.get("connected_q", False),
            mc_samples=c["mc_samples"], batch=c["batch"], q=c["q"], device=device,
        )
        det.model.load_state_dict(ckpt["model_state"])
        det.model.to(det.device)
        det.model.eval()
        det.mean_ = np.asarray(ckpt["mean"], dtype=np.float32)
        det.std_ = np.asarray(ckpt["std"], dtype=np.float32)
        det.threshold_ = float(ckpt["threshold"])
        return det

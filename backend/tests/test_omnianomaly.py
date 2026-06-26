import numpy as np
import pytest

torch = pytest.importorskip("torch")  # skip if the `ml` dep group isn't installed

from app.detectors.omnianomaly.detector import OmniAnomalyDetector  # noqa: E402


def _synthetic_series(n=600, d=5, seed=0):
    rng = np.random.default_rng(seed)
    base = np.cumsum(rng.normal(0, 0.05, size=(n, d)), axis=0)  # slow drift
    X = base + rng.normal(0, 0.1, size=(n, d))                  # + noise
    y = np.zeros(n, dtype=int)
    for i in (450, 451, 452, 500, 501, 550):                   # blatant injected spikes
        X[i] += rng.normal(6.0, 0.5, size=d)
        y[i] = 1
    return X.astype(np.float32), y


def test_omnianomaly_trains_and_scores():
    torch.manual_seed(0)
    X, y = _synthetic_series()
    det = OmniAnomalyDetector(
        n_features=X.shape[1], window=20, z_dim=3, hidden=16,
        n_flows=2, epochs=5, batch=32, lr=1e-2, mc_samples=5, seed=0,
    )
    history = det.fit(X[:400])  # train on the clean region only

    assert np.isfinite(history).all()
    assert history[-1] < history[0]          # ELBO loss decreased -> training works

    scores = det.score(X)
    assert scores.shape == (len(X),)
    assert np.isfinite(scores).all()

    pred = det.predict(X)
    assert set(np.unique(pred)).issubset({0, 1})

    # the blatant anomalies must score higher than normal points on average
    anom = y.astype(bool)
    assert scores[anom].mean() > scores[~anom].mean()

    # interpretation returns a per-dimension contribution aligned to each step
    contrib = det.interpret(X)
    assert contrib.shape == (len(X), X.shape[1])

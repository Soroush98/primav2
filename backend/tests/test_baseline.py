import numpy as np

from app.detectors.baseline import BaselineDetector
from app.eval.metrics import evaluate


def test_baseline_detects_injected_spikes_on_the_easy_regime():
    """A simple model should win the easy regime. Inject single-channel spikes
    into otherwise-normal multivariate windows; the MAD/EVT baseline must
    recover them with high strict F1 (mle-practices §2)."""
    rng = np.random.default_rng(1)
    n, d = 1_000, 10
    train = rng.normal(size=(n, d))
    test = rng.normal(size=(n, d))

    y = np.zeros(n, dtype=int)
    idx = rng.choice(n, size=50, replace=False)
    for i in idx:
        test[i, rng.integers(d)] += 8.0  # large single-channel deviation
    y[idx] = 1

    det = BaselineDetector().fit(train)
    res = evaluate(y, det.score(test))

    assert res.raw_best_f1 > 0.8, res.as_dict()
    assert res.auc_pr > 0.7, res.as_dict()

    # The EVT/POT threshold should flag roughly the anomalies, not everything.
    flagged = int(det.predict(test).sum())
    assert 0 < flagged < 200, flagged

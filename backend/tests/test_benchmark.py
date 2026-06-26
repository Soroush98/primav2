import numpy as np
import pytest

pytest.importorskip("torch")  # benchmark runs the OmniAnomaly arm

from app.eval.benchmark import benchmark_series, format_table  # noqa: E402


def _series(n=500, d=5, seed=0):
    rng = np.random.default_rng(seed)
    X = np.cumsum(rng.normal(0, 0.05, (n, d)), axis=0) + rng.normal(0, 0.1, (n, d))
    y = np.zeros(n, dtype=int)
    for i in (300, 301, 350, 400, 401, 450):
        X[i] += rng.normal(6.0, 0.5, size=d)
        y[i] = 1
    return X.astype(np.float32), y


def test_benchmark_reports_both_detectors_with_both_f1_variants():
    X, y = _series()
    results = benchmark_series(
        X[:250],  # clean train region (anomalies start at 300)
        X,
        y,
        omni_kwargs={"window": 20, "epochs": 3, "hidden": 16, "mc_samples": 3},
    )

    for detector in ("baseline", "omnianomaly"):
        r = results[detector]
        for key in ("raw_best_f1", "pa_best_f1", "auc_pr", "inflation_gap", "prevalence"):
            assert key in r, (detector, key)
        # point-adjusted F1 can only meet or exceed the strict F1 (the gap we track)
        assert r["pa_best_f1"] >= r["raw_best_f1"] - 1e-9

    table = format_table(results)
    assert "baseline" in table and "omnianomaly" in table

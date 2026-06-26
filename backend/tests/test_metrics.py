import numpy as np

from app.eval.metrics import best_f1, evaluate, point_adjust


def test_point_adjust_credits_whole_segment():
    y_true = np.array([0, 1, 1, 1, 0, 0])
    y_pred = np.array([0, 0, 1, 0, 0, 0])  # one hit inside the segment
    assert point_adjust(y_true, y_pred).tolist() == [False, True, True, True, False, False]


def test_point_adjust_ignores_hits_outside_segments():
    y_true = np.array([0, 1, 1, 0])
    y_pred = np.array([1, 0, 0, 0])  # fires only outside the segment
    assert point_adjust(y_true, y_pred).tolist() == [True, False, False, False]


def test_point_adjustment_inflates_a_random_scorer():
    """The trap (Kim et al. 2022): when anomalies occur in segments, a pure-noise
    scorer gets a near-perfect point-adjusted F1 while its strict F1 stays near
    chance. This is exactly why the gate reports both."""
    rng = np.random.default_rng(0)
    n = 20_000
    y_true = np.zeros(n, dtype=int)
    for start in range(500, n, 2_000):  # 10 segments of length 200 -> 10% prevalence
        y_true[start : start + 200] = 1
    scores = rng.random(n)  # no skill whatsoever

    res = evaluate(y_true, scores)

    assert res.pa_best_f1 > 0.8, res.as_dict()      # inflated to near-perfect
    assert res.raw_best_f1 < 0.3, res.as_dict()     # strict stays near chance
    assert res.inflation_gap > 0.5, res.as_dict()   # the gap the gate exists to show


def test_perfect_scorer_scores_one_both_ways():
    y_true = np.array([0, 0, 1, 1, 0, 1, 0])
    scores = y_true.astype(float)  # oracle
    assert best_f1(y_true, scores, adjusted=False)[2] == 1.0
    assert best_f1(y_true, scores, adjusted=True)[2] == 1.0

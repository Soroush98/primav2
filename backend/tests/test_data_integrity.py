"""Data-integrity tests (docs/test-cases/TC-DATA.md), in three layers:

1. Unit — the Python data-shaping logic every model consumes (`ffill`, series
   assembly invariants, synthetic-label injection) on small synthetic fixtures.
2. Artifact — the committed benchmark results in warehouse/ stay internally
   consistent (metrics in range, config ↔ results agreement), so a bad re-run
   can't silently replace them.
3. Live warehouse — the real `usage_5min` table honors the invariants that
   warehouse/alibaba_windowing.sql promises (reconciliation, uniqueness, domain
   ranges). Costs a few small BigQuery queries, so it only runs when explicitly
   requested:  BQ_INTEGRITY=1 uv run pytest tests/test_data_integrity.py -q
"""

import json
import os
import pathlib

import numpy as np
import pytest

from app.eval.alibaba import FEATURES, ffill, inject_anomalies

WAREHOUSE = pathlib.Path(__file__).resolve().parents[2] / "warehouse"

# ------------------------------------------------------------------ layer 1: unit


def test_ffill_fills_interior_gaps_forward():
    """TC-DATA-01: an interior NaN takes the last seen value (per feature)."""
    X = np.array([[1.0, 10.0], [np.nan, np.nan], [3.0, np.nan]])
    out = ffill(X)
    assert out[1].tolist() == [1.0, 10.0]
    assert out[2].tolist() == [3.0, 10.0]


def test_ffill_backfills_leading_gaps():
    """TC-DATA-02: leading NaNs (no prior value) take the first real value."""
    X = np.array([[np.nan], [np.nan], [7.0]])
    assert ffill(X).ravel().tolist() == [7.0, 7.0, 7.0]


def test_ffill_leaves_all_nan_column_nan():
    """TC-DATA-03: a feature with no data stays NaN — the loader must then DROP the
    machine rather than fabricate zeros (load_machines checks isnan after ffill)."""
    X = np.array([[np.nan, 1.0], [np.nan, 2.0]])
    out = ffill(X)
    assert np.isnan(out[:, 0]).all()
    assert not np.isnan(out[:, 1]).any()


def test_ffill_preserves_values_it_did_not_fill():
    """TC-DATA-04: gap-filling must never rewrite observed data."""
    rng = np.random.default_rng(0)
    X = rng.normal(50, 5, size=(200, len(FEATURES)))
    mask = rng.random(X.shape) < 0.1
    X_holed = X.copy()
    X_holed[mask] = np.nan
    out = ffill(X_holed.copy())
    assert np.array_equal(out[~mask], X[~mask])
    assert not np.isnan(out).any()


def test_inject_anomalies_labels_match_modified_regions():
    """TC-DATA-05: every labeled bin was actually modified-or-typed, labels stay
    inside the margins, and the clean copy is never mutated in place."""
    rng = np.random.default_rng(0)
    X = rng.normal(50, 5, size=(600, len(FEATURES)))
    X_orig = X.copy()
    gmin, gmax = X.min(axis=0), X.max(axis=0)

    X_anom, y, types = inject_anomalies(X, rng, gmin, gmax, events=6, margin=120)

    assert np.array_equal(X, X_orig), "input series was mutated in place"
    assert y.sum() > 0
    assert set(np.unique(y)) <= {0, 1}
    labeled = np.flatnonzero(y)
    assert labeled.min() >= 120 and labeled.max() < 600 - 120, "event leaked into margin"
    assert all(types[i] in ("spike", "context") for i in labeled)
    assert all(types[i] == "" for i in np.flatnonzero(y == 0))


def test_injected_spikes_exceed_the_global_range():
    """TC-DATA-06: 'spike' events must land far outside [gmin, gmax] — otherwise the
    benchmark's baseline-favorable anomaly type silently loses its meaning."""
    rng = np.random.default_rng(1)
    X = rng.normal(50, 5, size=(600, len(FEATURES)))
    gmin, gmax = X.min(axis=0), X.max(axis=0)
    X_anom, y, types = inject_anomalies(X, rng, gmin, gmax, events=8)
    spike_bins = [i for i in np.flatnonzero(y) if types[i] == "spike"]
    if not spike_bins:  # rng picked only context events — nothing to check
        pytest.skip("seed produced no spike events")
    for i in spike_bins:
        assert (X_anom[i] > gmax + 1e-9).any()


# -------------------------------------------------------------- layer 2: artifacts

METRICS_IN_UNIT_RANGE = ("prevalence", "auc_pr", "raw_best_f1", "pa_best_f1",
                         "raw_precision", "raw_recall")


def test_alibaba_benchmark_artifact_is_internally_consistent():
    """TC-DATA-07: the committed benchmark artifact parses, covers both detectors,
    and every rate/score metric is a valid probability."""
    doc = json.loads((WAREHOUSE / "alibaba_benchmark_results.json").read_text())
    assert doc["config"]["features"] == FEATURES
    overall = doc["results"]["overall"]
    for detector in ("baseline", "omnianomaly"):
        for metric in METRICS_IN_UNIT_RANGE:
            v = overall[detector][metric]
            assert 0.0 <= v <= 1.0, f"{detector}.{metric}={v} out of [0,1]"
    # both detectors were scored on the same injected ground truth
    assert overall["baseline"]["prevalence"] == overall["omnianomaly"]["prevalence"]


def test_smd_validation_artifact_is_internally_consistent():
    """TC-DATA-08: same checks for the SMD reproduction artifact, per machine."""
    doc = json.loads((WAREHOUSE / "smd_validation.json").read_text())
    assert doc["rows"], "artifact has no per-machine rows"
    for row in doc["rows"]:
        for detector in ("baseline", "omnianomaly"):
            for metric in METRICS_IN_UNIT_RANGE:
                v = row[detector][metric]
                assert 0.0 <= v <= 1.0, f"{row['machine']}: {detector}.{metric}={v}"


# --------------------------------------------------------- layer 3: live warehouse

pytestmark_live = pytest.mark.skipif(
    not os.getenv("BQ_INTEGRITY"),
    reason="live BigQuery data-quality checks run only with BQ_INTEGRITY=1 (costs queries)",
)


@pytestmark_live
class TestLiveWarehouseQuality:
    """The invariants warehouse/alibaba_windowing.sql promises, checked on the real
    table. Each query is a small aggregate — pennies, not table scans."""

    DATASET = "primav2.alibaba_cluster"

    @pytest.fixture(scope="class")
    def bq(self):
        from google.cloud import bigquery

        return bigquery.Client(project="primav2")

    def _scalar(self, bq, sql):
        return list(bq.query(sql).result())[0][0]

    def test_no_duplicate_machine_bin_keys(self, bq):
        """TC-DATA-09: (machine_id, bin) is the declared key of usage_5min."""
        dupes = self._scalar(
            bq,
            f"""SELECT COUNT(*) FROM (
                  SELECT machine_id, bin FROM `{self.DATASET}.usage_5min`
                  GROUP BY machine_id, bin HAVING COUNT(*) > 1)""",
        )
        assert dupes == 0

    def test_row_count_reconciles_with_raw_table(self, bq):
        """TC-DATA-10: every raw sample is accounted for in exactly one bin."""
        diff = self._scalar(
            bq,
            f"""SELECT (SELECT SUM(n_samples) FROM `{self.DATASET}.usage_5min`)
                     - (SELECT COUNT(*)      FROM `{self.DATASET}.machine_usage`)""",
        )
        assert diff == 0

    def test_metric_domains_hold(self, bq):
        """TC-DATA-11: bin means stay in the documented [0,100] domains."""
        bad = self._scalar(
            bq,
            f"""SELECT COUNT(*) FROM `{self.DATASET}.usage_5min`
                WHERE cpu NOT BETWEEN 0 AND 100
                   OR mem NOT BETWEEN 0 AND 100
                   OR (disk_io IS NOT NULL AND disk_io NOT BETWEEN 0 AND 100)""",
        )
        assert bad == 0

    def test_disk_io_null_only_when_every_sample_was_abnormal(self, bq):
        """TC-DATA-12: NULL disk_io must mean 'all samples were -1/101 markers',
        never a windowing bug."""
        bad = self._scalar(
            bq,
            f"""SELECT COUNT(*) FROM `{self.DATASET}.usage_5min`
                WHERE disk_io IS NULL AND n_disk_abnormal < n_samples""",
        )
        assert bad == 0

    def test_bins_and_counts_are_sane(self, bq):
        """TC-DATA-13: no empty or negative bins; n_samples >= n_disk_abnormal."""
        bad = self._scalar(
            bq,
            f"""SELECT COUNT(*) FROM `{self.DATASET}.usage_5min`
                WHERE bin < 0 OR n_samples <= 0 OR n_disk_abnormal > n_samples""",
        )
        assert bad == 0

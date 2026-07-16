# TC-DATA — data integrity (SQL warehouse & Python data shaping)

Automation: [backend/tests/test_data_integrity.py](../../backend/tests/test_data_integrity.py).
Layers 1–2 (unit + artifact) run in CI; layer 3 (live warehouse) is opt-in:
`BQ_INTEGRITY=1 uv run pytest tests/test_data_integrity.py` — run it after any
data reload or change to [warehouse/alibaba_windowing.sql](../../warehouse/alibaba_windowing.sql).
Priority follows risk R3.

## Layer 1 — data-shaping logic every model consumes (CI)

| ID | Title | Req | Pri | Given / When / Then | Automation |
|----|-------|-----|-----|---------------------|------------|
| TC-DATA-01 | Interior gaps forward-fill | REQ-07 | P1 | Given a series with interior NaNs / When `ffill` runs / Then each NaN takes the last seen value, per feature | `test_ffill_fills_interior_gaps_forward` |
| TC-DATA-02 | Leading gaps back-fill | REQ-07 | P1 | Given leading NaNs / When filled / Then they take the first real value | `test_ffill_backfills_leading_gaps` |
| TC-DATA-03 | All-NaN feature stays NaN | REQ-07 | P1 | Given a feature with no data / When filled / Then it stays NaN so the loader drops the machine rather than fabricating zeros | `test_ffill_leaves_all_nan_column_nan` |
| TC-DATA-04 | Fill never rewrites observed data | REQ-07 | P1 | Given 10% random holes / When filled / Then every observed value is bit-identical and no NaN remains | `test_ffill_preserves_values_it_did_not_fill` |
| TC-DATA-05 | Injection labels match modified regions | REQ-07 | P1 | Given a clean series / When anomalies are injected / Then labels ⊆ modified bins, margins respected, input not mutated | `test_inject_anomalies_labels_match_modified_regions` |
| TC-DATA-06 | Spikes exceed the global range | REQ-07 | P2 | Given injected spike events / When inspected / Then values land beyond gmax — the benchmark's anomaly types keep their meaning | `test_injected_spikes_exceed_the_global_range` |

## Layer 2 — committed benchmark artifacts (CI)

| ID | Title | Req | Pri | Given / When / Then | Automation |
|----|-------|-----|-----|---------------------|------------|
| TC-DATA-07 | Alibaba benchmark artifact consistent | REQ-07 | P2 | Given `warehouse/alibaba_benchmark_results.json` / When validated / Then features match the code's FEATURES, every rate metric ∈ [0,1], both detectors share one ground truth | `test_alibaba_benchmark_artifact_is_internally_consistent` |
| TC-DATA-08 | SMD validation artifact consistent | REQ-07 | P2 | Same checks per machine row for `smd_validation.json` | `test_smd_validation_artifact_is_internally_consistent` |

## Layer 3 — live warehouse quality (opt-in, real queries)

The invariants `alibaba_windowing.sql` promises, checked on the real
`usage_5min` table with small aggregates.

| ID | Title | Req | Pri | Given / When / Then | Automation |
|----|-------|-----|-----|---------------------|------------|
| TC-DATA-09 | No duplicate (machine_id, bin) keys | REQ-07 | P1 | Given the live table / When grouped by key / Then zero duplicates | `test_no_duplicate_machine_bin_keys` |
| TC-DATA-10 | Row counts reconcile with raw table | REQ-07 | P1 | Given SUM(n_samples) vs COUNT(*) of `machine_usage` / When compared / Then equal — every raw sample lands in exactly one bin | `test_row_count_reconciles_with_raw_table` |
| TC-DATA-11 | Metric domains hold | REQ-07 | P1 | Given all bin means / When range-checked / Then cpu/mem/disk_io ∈ [0,100] (disk_io may be NULL) | `test_metric_domains_hold` |
| TC-DATA-12 | NULL disk_io only when all samples abnormal | REQ-07 | P1 | Given rows with NULL disk_io / When cross-checked / Then n_disk_abnormal == n_samples — NULL means "all markers", never a windowing bug | `test_disk_io_null_only_when_every_sample_was_abnormal` |
| TC-DATA-13 | Bins & counts sane | REQ-07 | P2 | Given all rows / When checked / Then bin ≥ 0, n_samples > 0, n_disk_abnormal ≤ n_samples | `test_bins_and_counts_are_sane` |

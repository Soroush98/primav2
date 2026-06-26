-- primav2 — Alibaba cluster-trace-v2018 → regular per-machine TIME series.
-- Built against the real loaded schema of `primav2.alibaba_cluster.machine_usage`
-- (~247M rows · 4023 machines · 8 days · verified 2026-06-26).
--
-- ─────────────────────────────────────────────────────────────────────────────
-- WHY THIS DATASET: unlike NF-UQ-NIDS-v2 (no timestamp → count-windows in an
-- arbitrary order), this trace has a real `time_stamp` (seconds from t0). It is
-- "SMD at cloud scale": per-machine resource metrics over time. Resampling to
-- fixed bins yields a REGULAR multivariate time series with genuine temporal
-- structure — the regime OmniAnomaly was built for.
--
-- DESIGN:
--  • Resample to fixed BIN_SECONDS bins; each bin = the mean of the raw samples
--    that fall in it (raw sampling is irregular, ~10–100s). `bin` is the integer
--    timestep index, so ORDER BY bin is REAL chronological order per machine.
--  • Features = the 5 metrics with full coverage: cpu, mem, net_in, net_out,
--    disk_io. (mem_gps / mkpi are 79% null in the trace → dropped.)
--  • disk_io_percent carries abnormal markers (-1 / 101, ~0.12% of rows). They are
--    excluded from the mean (they'd corrupt it) and counted as `n_disk_abnormal`
--    — a real, if sparse, weak-anomaly signal for cross-checking the detectors.
--  • `n_samples` = raw samples per bin (coverage; lets the benchmark drop sparse
--    bins / low-coverage machines and forward-fill the few gaps for a regular seq).
--
-- No anomaly labels ship with the trace (machine_meta.status is ~all USING), so
-- the benchmark (scripts/run_alibaba_benchmark.py) trains on normal data and uses
-- synthetic injection (a mix of point / level-shift / contextual-freeze types),
-- with `n_disk_abnormal` as a real-data cross-check.
-- ─────────────────────────────────────────────────────────────────────────────

DECLARE BIN_SECONDS INT64 DEFAULT 300;   -- 5-minute bins → ~2304 timesteps/machine over 8 days

CREATE OR REPLACE TABLE `primav2.alibaba_cluster.usage_5min`
CLUSTER BY machine_id AS
SELECT
  machine_id,
  DIV(time_stamp, BIN_SECONDS)                                          AS bin,
  AVG(cpu_util_percent)                                                 AS cpu,
  AVG(mem_util_percent)                                                 AS mem,
  AVG(net_in)                                                           AS net_in,
  AVG(net_out)                                                          AS net_out,
  AVG(IF(disk_io_percent BETWEEN 0 AND 100, disk_io_percent, NULL))     AS disk_io,
  COUNTIF(disk_io_percent < 0 OR disk_io_percent > 100)                 AS n_disk_abnormal,
  COUNT(*)                                                              AS n_samples
FROM `primav2.alibaba_cluster.machine_usage`
GROUP BY machine_id, bin;

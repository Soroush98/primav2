#!/usr/bin/env bash
# Download Alibaba cluster-trace-v2018 machine telemetry and load it into BigQuery.
#
# This is the "SMD at cloud scale" dataset: per-machine resource metrics
# (CPU/mem/net/disk) sampled ~every 10–100s over 8 days for ~4000 machines —
# a genuine multivariate TIME SERIES (real `time_stamp`), unlike NF-UQ-NIDS-v2
# which has no timestamp. ~247M rows of machine_usage (8.4GB uncompressed).
#
# No anomaly labels ship with the trace (machine_meta.status is ~all USING), so
# the benchmark trains on normal data and uses synthetic injection + the built-in
# disk_io_percent abnormals (-1/101) — see scripts/run_alibaba_benchmark.py.
#
# Usage:  bash scripts/get_alibaba.sh
# Env overrides: PROJECT, DATASET, LOCATION, KEEP_LOCAL=1

set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
export CLOUDSDK_CORE_DISABLE_PROMPTS=1

PROJECT="${PROJECT:-primav2}"
DATASET="${DATASET:-alibaba_cluster}"
LOCATION="${LOCATION:-US}"
BASE_URL="https://aliopentrace.oss-cn-beijing.aliyuncs.com/v2018Traces"
DATA_DIR="$(cd "$(dirname "$0")/.." && pwd)/data/alibaba"
mkdir -p "$DATA_DIR"

# Headerless CSVs → explicit schemas (from the trace's schema.txt).
USAGE_SCHEMA="machine_id:STRING,time_stamp:INT64,cpu_util_percent:INT64,mem_util_percent:INT64,mem_gps:FLOAT64,mkpi:INT64,net_in:FLOAT64,net_out:FLOAT64,disk_io_percent:FLOAT64"
META_SCHEMA="machine_id:STRING,time_stamp:INT64,failure_domain_1:INT64,failure_domain_2:STRING,cpu_num:INT64,mem_size:INT64,status:STRING"

fetch() {  # name
  local f="$1"
  if [[ ! -f "$DATA_DIR/$f.csv" ]]; then
    echo ">> downloading $f.tar.gz ..."
    curl -fsSL -o "$DATA_DIR/$f.tar.gz" "$BASE_URL/$f.tar.gz"
    tar xzf "$DATA_DIR/$f.tar.gz" -C "$DATA_DIR"
  fi
  echo ">> $f.csv on disk: $(du -h "$DATA_DIR/$f.csv" | cut -f1)"
}

fetch machine_meta
fetch machine_usage

echo ">> ensuring dataset ${PROJECT}:${DATASET} ..."
bq --project_id="$PROJECT" --location="$LOCATION" mk -f --dataset "${PROJECT}:${DATASET}" >/dev/null

echo ">> loading machine_meta ..."
bq --project_id="$PROJECT" load --source_format=CSV --replace \
  "${PROJECT}:${DATASET}.machine_meta" "$DATA_DIR/machine_meta.csv" "$META_SCHEMA"

echo ">> loading machine_usage (~247M rows, the long step) ..."
bq --project_id="$PROJECT" load --source_format=CSV --replace \
  "${PROJECT}:${DATASET}.machine_usage" "$DATA_DIR/machine_usage.csv" "$USAGE_SCHEMA"

echo "=== STATS ==="
bq --project_id="$PROJECT" query --use_legacy_sql=false --format=pretty \
  "SELECT COUNT(*) AS n, COUNT(DISTINCT machine_id) AS machines,
          ROUND((MAX(time_stamp)-MIN(time_stamp))/86400,2) AS span_days
   FROM \`${PROJECT}.${DATASET}.machine_usage\`"

if [[ "${KEEP_LOCAL:-0}" != "1" ]]; then
  rm -f "$DATA_DIR"/machine_usage.csv "$DATA_DIR"/*.tar.gz && echo ">> removed large local files (KEEP_LOCAL=1 to keep)."
fi
echo ">> DONE"

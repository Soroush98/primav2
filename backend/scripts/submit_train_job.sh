#!/usr/bin/env bash
# Submit the global OmniAnomaly training as a Vertex AI CUSTOM JOB.
#
# A custom job is run-to-completion: it spins up a GPU, trains, writes the
# checkpoint to GCS, and TERMINATES — it is not a persistent endpoint, so there is
# no idle GPU cost. Typical run: ~30-90 min on 1x L4 ≈ $1-3. The only thing left
# behind is the checkpoint in GCS (a few MB, ~free), which Cloud Run loads at serve.
#
# Usage:
#   cd backend && ./scripts/submit_train_job.sh
# Override any knob inline, e.g.:
#   HIDDEN=256 N_FLOWS=20 EPOCHS=40 N_TRAIN=500 ./scripts/submit_train_job.sh
set -euo pipefail

# ---- project / infra (override via env) -------------------------------------
PROJECT="${PROJECT:-primav2}"
REGION="${REGION:-us-central1}"
RUNTIME_SA="${RUNTIME_SA:-prima-run@${PROJECT}.iam.gserviceaccount.com}"
BUCKET="${BUCKET:-${PROJECT}-models}"
CHECKPOINT_DIR="${CHECKPOINT_DIR:-gs://${BUCKET}/omni}"
REPO="${REPO:-${REGION}-docker.pkg.dev/${PROJECT}/web}"
IMAGE="${IMAGE:-${REPO}/omni-train:latest}"

# ---- GPU + training config (override via env) -------------------------------
MACHINE_TYPE="${MACHINE_TYPE:-g2-standard-4}"   # g2 = L4. (n1-standard-8 for T4.)
ACCELERATOR="${ACCELERATOR:-NVIDIA_L4}"         # or NVIDIA_TESLA_T4 (cheaper, slower)
N_TRAIN="${N_TRAIN:-300}"; N_VAL="${N_VAL:-40}"
WINDOW="${WINDOW:-100}"; Z_DIM="${Z_DIM:-3}"; HIDDEN="${HIDDEN:-128}"
N_FLOWS="${N_FLOWS:-10}"; EPOCHS="${EPOCHS:-30}"; BATCH="${BATCH:-256}"
MC_SAMPLES="${MC_SAMPLES:-8}"; SEEDS="${SEEDS:-0,1,2}"

echo ">> project=$PROJECT region=$REGION image=$IMAGE checkpoint=$CHECKPOINT_DIR"

# 1. Ensure the Artifact Registry repo + GCS bucket exist; let the runtime SA write
#    the checkpoint. (No-ops if they already exist.)
gcloud artifacts repositories create web --repository-format=docker \
  --location="$REGION" --project="$PROJECT" 2>/dev/null || true
gcloud storage buckets create "gs://${BUCKET}" --location="$REGION" \
  --project="$PROJECT" 2>/dev/null || true
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${RUNTIME_SA}" --role=roles/storage.objectAdmin >/dev/null

# 2. Build + push the GPU training image with Cloud Build.
#    (--tag can't name a non-default Dockerfile, so use an inline build config.)
#    SKIP_BUILD=1 reuses the already-pushed image (skips the ~7-min rebuild).
if [ -z "${SKIP_BUILD:-}" ]; then
  echo ">> building training image ..."
  BUILD_CFG="$(mktemp)"
  cat >"$BUILD_CFG" <<YAML
steps:
  - name: gcr.io/cloud-builders/docker
    args: ["build", "-f", "Dockerfile.train", "-t", "${IMAGE}", "."]
images: ["${IMAGE}"]
YAML
  gcloud builds submit --project="$PROJECT" --config="$BUILD_CFG" .
  rm -f "$BUILD_CFG"
else
  echo ">> SKIP_BUILD=1 — reusing $IMAGE"
fi

# 3. Worker pool spec (1 GPU replica) — env carries the training config.
#    SPOT=1 uses Spot/preemptible GPUs (cheaper, available when on-demand quota is
#    0; the job can be preempted and must be re-run if so).
SPEC="$(mktemp)"
{
  if [ -n "${SPOT:-}" ]; then printf 'scheduling:\n  strategy: SPOT\n'; fi
  cat <<YAML
workerPoolSpecs:
  - machineSpec:
      machineType: ${MACHINE_TYPE}
      acceleratorType: ${ACCELERATOR}
      acceleratorCount: 1
    replicaCount: 1
    containerSpec:
      imageUri: ${IMAGE}
      env:
        - name: PROJECT
          value: "${PROJECT}"
        - name: CHECKPOINT_DIR
          value: "${CHECKPOINT_DIR}"
        - name: N_TRAIN
          value: "${N_TRAIN}"
        - name: N_VAL
          value: "${N_VAL}"
        - name: WINDOW
          value: "${WINDOW}"
        - name: Z_DIM
          value: "${Z_DIM}"
        - name: HIDDEN
          value: "${HIDDEN}"
        - name: N_FLOWS
          value: "${N_FLOWS}"
        - name: EPOCHS
          value: "${EPOCHS}"
        - name: BATCH
          value: "${BATCH}"
        - name: MC_SAMPLES
          value: "${MC_SAMPLES}"
        - name: SEEDS
          value: "${SEEDS}"
YAML
} > "$SPEC"

# 4. Submit. Runs to completion, then the GPU is released automatically.
echo ">> submitting custom job ..."
gcloud ai custom-jobs create \
  --project="$PROJECT" --region="$REGION" \
  --display-name="omni-train-h${HIDDEN}-f${N_FLOWS}-e${EPOCHS}" \
  --service-account="$RUNTIME_SA" \
  --config="$SPEC"

rm -f "$SPEC"
echo ">> done. Watch it:"
echo "   gcloud ai custom-jobs list --region=$REGION --project=$PROJECT"
echo "   checkpoint will appear at: ${CHECKPOINT_DIR}/omni_global.pt"

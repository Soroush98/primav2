# Deploying primav2

Both services run on **Google Cloud Run** (stateless containers). The backend talks
to Vertex AI (Gemini) and BigQuery via the attached **service account** — no keys.

```
 Browser ──▶ Frontend (Cloud Run, Next.js) ──▶ Backend (Cloud Run, FastAPI) ──▶ Vertex AI + BigQuery
```

> **Order matters** (two URLs reference each other): deploy the **backend first**,
> build the **frontend** with the backend URL, then point the backend's CORS at the
> frontend URL.

## 0. One-time project setup

```bash
export PROJECT=primav2
export REGION=us-central1
gcloud config set project $PROJECT

# Enable the APIs.
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com aiplatform.googleapis.com bigquery.googleapis.com

# Least-privilege runtime service account (SECURITY.md rec #1): Vertex + read-only BigQuery.
gcloud iam service-accounts create prima-run --display-name="primav2 Cloud Run"
SA="prima-run@$PROJECT.iam.gserviceaccount.com"
for ROLE in roles/aiplatform.user roles/bigquery.jobUser roles/bigquery.dataViewer; do
  gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA" --role="$ROLE"
done
# Tighter alternative for dataViewer: grant it on the dataset only, not project-wide.
```

## 1. Backend → Cloud Run

Source-deploy builds [`backend/Dockerfile`](backend/Dockerfile) with Cloud Build:

```bash
cd backend
gcloud run deploy prima-backend \
  --source . --region $REGION --service-account $SA \
  --allow-unauthenticated --memory=1Gi --min-instances=1 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=global,GEMINI_MODEL=gemini-2.5-flash,BIGQUERY_DATASET=alibaba_cluster,OMNI_CHECKPOINT_URI=gs://$PROJECT-models/omni/omni_global.pt,CHRONOS_MODEL=amazon/chronos-bolt-tiny,FRONTEND_ORIGIN=*"

BACKEND_URL=$(gcloud run services describe prima-backend --region $REGION --format='value(status.url)')
echo "Backend: $BACKEND_URL"      # e.g. https://prima-backend-xxxx.us-central1.run.app
```

`FRONTEND_ORIGIN=*` is a temporary placeholder; we lock it in step 3.

> **Auth note:** `--allow-unauthenticated` makes the API public. It is currently
> unauthenticated (SECURITY.md rec #3) — keep it private with `--no-allow-unauthenticated`
> and call it with an identity token, or put it behind IAP / an API gateway before
> exposing it for real.

## 2. Frontend → Cloud Run

`NEXT_PUBLIC_API_URL` is **baked at build time**, so it's a Docker build arg. Build the
image with the backend URL, push to Artifact Registry, then deploy:

```bash
cd ../frontend
REPO=$REGION-docker.pkg.dev/$PROJECT/web
gcloud artifacts repositories create web --repository-format=docker --location=$REGION 2>/dev/null || true
gcloud auth configure-docker $REGION-docker.pkg.dev -q

gcloud builds submit --tag $REPO/prima-frontend \
  --substitutions _URL="$BACKEND_URL" \
  --config - <<'YAML'
steps:
  - name: gcr.io/cloud-builders/docker
    args: ["build","--build-arg","NEXT_PUBLIC_API_URL=${_URL}","-t","$_REPO/prima-frontend","."]
YAML
# (Simpler if you have local Docker:)
#   docker build --build-arg NEXT_PUBLIC_API_URL=$BACKEND_URL -t $REPO/prima-frontend .
#   docker push $REPO/prima-frontend

gcloud run deploy prima-frontend \
  --image $REPO/prima-frontend --region $REGION --allow-unauthenticated

FRONTEND_URL=$(gcloud run services describe prima-frontend --region $REGION --format='value(status.url)')
echo "Frontend: $FRONTEND_URL"
```

## 3. Lock CORS to the real frontend

```bash
gcloud run services update prima-backend --region $REGION \
  --update-env-vars "FRONTEND_ORIGIN=$FRONTEND_URL"
```

Open `$FRONTEND_URL` — done.

---

## Simpler alternative: frontend on Vercel

Next.js's native host removes the build-arg dance:

```bash
cd frontend && npx vercel        # link the project, then:
npx vercel env add NEXT_PUBLIC_API_URL   # paste the backend URL
npx vercel --prod
```

Then set the backend's `FRONTEND_ORIGIN` to the Vercel URL (step 3).

## Local smoke test of the containers (optional)

```bash
docker build -t prima-backend ./backend
docker run -p 8000:8080 -e GOOGLE_CLOUD_PROJECT=primav2 \
  -e GOOGLE_APPLICATION_CREDENTIALS=/adc.json -v ~/.config/gcloud/application_default_credentials.json:/adc.json \
  prima-backend
# → http://localhost:8000/api/health
```

## Notes & costs
- **One image, no torch.** The backend image installs production deps only (no `ml`
  group) — OmniAnomaly training is offline, not in the request path.
- **No idle GPU.** Cloud Run scales to zero; the only spend in the request path is
  managed Gemini calls + BigQuery bytes scanned (capped by `bigquery_max_bytes_billed`).
- **Region:** keep BigQuery, Cloud Run, and Vertex in compatible regions to avoid
  egress and latency.

---

## CI/CD — deploy on push (GitHub Actions)

[`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) runs on push to `main`:
**verify** (ruff + pytest + `next build`) → **backend** deploy → **frontend** build
(with the backend URL baked in) + deploy + CORS lock. Auth is **keyless via Workload
Identity Federation** — no service-account JSON is ever stored in GitHub.

### One-time setup

```bash
export PROJECT=primav2 REPO=Soroush98/primav2
PNUM=$(gcloud projects describe $PROJECT --format='value(projectNumber)')

# 1. A deployer service account the workflow impersonates.
gcloud iam service-accounts create prima-deployer --display-name="primav2 CI deployer"
DEPLOYER="prima-deployer@$PROJECT.iam.gserviceaccount.com"
for ROLE in roles/run.admin roles/iam.serviceAccountUser \
            roles/cloudbuild.builds.editor roles/artifactregistry.admin roles/storage.admin; do
  gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$DEPLOYER" --role="$ROLE"
done

# 2. Workload Identity Federation pool + provider, scoped to THIS repo only.
gcloud iam workload-identity-pools create github --location=global --display-name="GitHub"
gcloud iam workload-identity-pools providers create-oidc github \
  --location=global --workload-identity-pool=github --display-name="GitHub OIDC" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='$REPO'"

# 3. Let the repo impersonate the deployer SA.
gcloud iam service-accounts add-iam-policy-binding $DEPLOYER \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$PNUM/locations/global/workloadIdentityPools/github/attribute.repository/$REPO"
```

### GitHub repo variables

Settings → Secrets and variables → **Actions → Variables** (these are *variables*, not
secrets — none are sensitive; WIF needs no key):

| Variable | Value |
|---|---|
| `GCP_PROJECT` | `primav2` |
| `GCP_REGION` | e.g. `us-central1` |
| `GCP_WIF_PROVIDER` | `projects/<PNUM>/locations/global/workloadIdentityPools/github/providers/github` |
| `GCP_DEPLOYER_SA` | `prima-deployer@primav2.iam.gserviceaccount.com` |
| `GCP_RUNTIME_SA` | `prima-run@primav2.iam.gserviceaccount.com` (from step 0) |

```bash
gh variable set GCP_PROJECT --body primav2
gh variable set GCP_REGION --body us-central1
gh variable set GCP_WIF_PROVIDER --body "projects/$PNUM/locations/global/workloadIdentityPools/github/providers/github"
gh variable set GCP_DEPLOYER_SA --body "prima-deployer@$PROJECT.iam.gserviceaccount.com"
gh variable set GCP_RUNTIME_SA --body "prima-run@$PROJECT.iam.gserviceaccount.com"
```

Push to `main` and the Actions tab shows the pipeline. (The runtime SA `prima-run` and
its read-only BigQuery + Vertex roles come from **step 0** above.)


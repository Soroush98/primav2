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
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=global,GEMINI_MODEL=gemini-2.5-flash,BIGQUERY_DATASET=alibaba_cluster,FRONTEND_ORIGIN=*"

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

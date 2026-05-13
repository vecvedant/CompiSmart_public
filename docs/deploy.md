# Deploy to Cloud Run via GitHub Actions

One-time setup. After this, every push to `main` deploys automatically.

## What you'll set up

- A GCP service account with just enough permissions to deploy Cloud Run.
- A JSON key for that service account, stored as a GitHub Actions secret.
- The five runtime API keys, also stored as GitHub Actions secrets.

## 0) Prereqs

- A **GCP project** (the one your Gemini API key already lives under is fine).
- The **`gcloud` CLI** installed locally, signed in as a project owner.
- A **GitHub repo** for this codebase.

If you don't have `gcloud` yet: <https://cloud.google.com/sdk/docs/install>.

---

## 1) Pick a project ID and region

```bash
# Use your existing GCP project ID. List them if you forgot:
gcloud projects list

# Set as the active project for the rest of this guide:
export PROJECT_ID="your-project-id-here"
gcloud config set project "$PROJECT_ID"

# us-central1 is the canonical free-tier region. us-east1 also works.
export REGION="us-central1"
```

---

## 2) Enable the APIs Cloud Run needs

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com
```

Three APIs:
- **Cloud Run** — runs the container.
- **Cloud Build** — builds the Docker image from the Dockerfile (`gcloud run deploy --source .` shells out to it).
- **Artifact Registry** — stores the built image.

---

## 3) Create a service account for GitHub Actions

```bash
# Create the SA (name can be anything; we use rag-returns-deployer):
gcloud iam service-accounts create rag-returns-deployer \
  --display-name "GitHub Actions deployer for rag-returns"

export SA_EMAIL="rag-returns-deployer@${PROJECT_ID}.iam.gserviceaccount.com"

# Grant the roles `gcloud run deploy --source .` actually needs.
# (Yes, it's six. Each one covers a step of the deploy.)
for role in \
    roles/run.admin \
    roles/iam.serviceAccountUser \
    roles/cloudbuild.builds.editor \
    roles/artifactregistry.admin \
    roles/storage.admin \
    roles/logging.viewer
do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="$role" \
    --condition=None \
    --quiet
done
```

---

## 4) Create a JSON key for the service account

```bash
gcloud iam service-accounts keys create ~/rag-returns-sa.json \
  --iam-account "$SA_EMAIL"
```

This drops `rag-returns-sa.json` in your home directory. **Treat it like a password** — anyone with this file can deploy to your project.

You'll paste the FULL CONTENTS of this file (the JSON, not the path) into the `GCP_SA_KEY` GitHub secret in the next step. After that, **delete the local file**.

---

## 5) Push the repo to GitHub

```bash
# From the project root.
# (a) Create a new repo on github.com (UI), don't init with README/license.
# (b) Add it as the remote and push:

git remote add origin https://github.com/<your-username>/<repo-name>.git
git push -u origin main
```

---

## 6) Add the 7 GitHub Actions secrets

In your repo on github.com:
**Settings → Secrets and variables → Actions → New repository secret.**

Add each of these:

| Secret name | Value |
|---|---|
| `GCP_PROJECT_ID` | Your project ID (e.g. `my-project-12345`) |
| `GCP_SA_KEY` | The full JSON contents of `~/rag-returns-sa.json` |
| `APIFY_TOKEN` | Your Apify token |
| `DEEPGRAM_API_KEY` | Your Deepgram key |
| `GOOGLE_API_KEY` | Your Gemini key (use this name even if your `.env` calls it `GEMINI_API_KEY`) |
| `QDRANT_URL` | Your Qdrant Cloud URL |
| `QDRANT_API_KEY` | Your Qdrant API key |

After saving the last one, **delete the local `~/rag-returns-sa.json` file**:

```bash
rm ~/rag-returns-sa.json
```

---

## 7) Trigger the first deploy

Two options:

**Option A — push any commit to `main`:**
```bash
git commit --allow-empty -m "ci: trigger first cloud run deploy"
git push
```

**Option B — manual run from GitHub:**
Repo on github.com → **Actions** → "Deploy to Cloud Run" → "Run workflow".

The first build takes **~5–8 minutes** (Docker build + BGE model download into the image + push to Artifact Registry + Cloud Run rollout). Subsequent builds are faster (~2 min) thanks to layer caching.

---

## 8) Verify the live URL

After the workflow finishes, the last step of the Actions log prints the service URL, e.g.:
```
https://rag-returns-xxxxxxxxxx-uc.a.run.app
```

Quick smoke checks:
```bash
SERVICE_URL="https://rag-returns-xxxxxxxxxx-uc.a.run.app"

# Should return {"ok":true}
curl "$SERVICE_URL/api/health"

# Real ingest (this hits Apify/Deepgram/Gemini/Qdrant — takes 60–90s)
curl -X POST "$SERVICE_URL/api/ingest" \
  -H "Content-Type: application/json" \
  -d '{"url_a":"<your YouTube URL>","url_b":"<your IG URL>"}'
```

---

## Cost expectation on free tier

Cloud Run free tier per month:
- 2,000,000 requests
- 360,000 vCPU-seconds (≈ 100 hours at 1 vCPU)
- 180,000 GiB-seconds (≈ 50 hours at 1 GiB)

For a screening-demo workload, you'll use **well under 1 hour/month**. Total runtime cost: **$0**. The only paid line items would be Apify (~$0.001/video on free credit) and Deepgram (your $200 credit covers ~75 hours of audio).

## Cold-start mitigation (optional)

By default Cloud Run scales to zero. First request after idle = ~5–10 second cold start (loading FastAPI + BGE into RAM).

If a live demo can't tolerate that:
- Add `--min-instances=1` to the deploy command in `.github/workflows/deploy.yml`. Costs ~$5/mo to keep one instance warm. **Not free anymore.**
- OR set up cron-job.org to ping `/api/health` every 10 min for free.

For the screen demo, pre-warm with one curl hit a minute before the call.

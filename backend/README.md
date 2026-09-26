# Backend

Always-on controller that runs on your small server.

Responsibilities:

- durable workflow metadata
- upload input images to R2
- presign input URLs
- render API workflow placeholders
- enqueue Salad jobs
- poll Salad job state
- turn returned `s3://...` output URIs into temporary signed HTTPS URLs

## Run

```bash
cp .env.example .env
docker build -t qwen-controller-backend .
docker run \
  --env-file .env \
  -p 8100:8000 \
  -v $(pwd)/data:/app/data \
  qwen-controller-backend
```

Health:

```bash
curl http://127.0.0.1:8100/health
```

## Workflow API

Save:

```bash
curl -X PUT http://127.0.0.1:8100/api/workflows/01-general-editor \
  -H 'Content-Type: application/json' \
  -d @workflow-record.json
```

The `api_prompt` field must be ComfyUI **API Format**.

## Important security note

Do not expose this backend directly to the internet.

Recommended path:

```text
Cloudflare Access
 -> Nginx
 -> frontend/backend
```

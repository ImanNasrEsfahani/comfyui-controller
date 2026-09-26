# Frontend

Lightweight always-on controller UI.

It does not contain ComfyUI itself and therefore needs no GPU.

Build:

```bash
docker build -t qwen-controller-frontend .
docker run -p 3100:80 qwen-controller-frontend
```

The frontend expects the API under the same origin at `/api`.

The host Nginx config in `../infra/nginx/` sends `/api/` to the backend and `/` to this frontend.

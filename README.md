# Qwen ComfyUI Controller

یک monorepo واحد برای بخش دائمی پروژه روی سرور شخصی.

## ساختار

```text
qwen-comfyui-controller/
├── frontend/
├── backend/
├── deploy/
│   └── nginx/
├── scripts/
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

این repository شامل Salad GPU Worker نیست. Worker یک deployment جدا روی SaladCloud است و Backend از طریق Salad Job Queue با آن ارتباط می‌گیرد.

## نصب روی سرور

```bash
git clone <YOUR_REPOSITORY_URL>
cd qwen-comfyui-controller
cp .env.example .env
nano .env
docker compose up -d --build
```

یا:

```bash
./scripts/start.sh
```

## سرویس‌ها

- Frontend: `127.0.0.1:3100`
- Backend: `127.0.0.1:8100`
- SQLite: داخل Docker volume دائمی `controller_data`
- Nginx host: `deploy/nginx/comfyui.imannasr.com.conf`

Frontend و Backend در یک repository و یک Docker Compose مدیریت می‌شوند.

## دستورات

```bash
./scripts/start.sh
./scripts/logs.sh
./scripts/stop.sh
./scripts/update.sh
```

## Nginx

```bash
sudo cp deploy/nginx/comfyui.imannasr.com.conf /etc/nginx/sites-available/comfyui.imannasr.com
sudo ln -s /etc/nginx/sites-available/comfyui.imannasr.com /etc/nginx/sites-enabled/comfyui.imannasr.com
sudo nginx -t
sudo systemctl reload nginx
```

سپس DNS دامنه `comfyui.imannasr.com` را به IP همین سرور متصل کنید.

from dataclasses import dataclass
import os

def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "qwen-comfyui-controller")
    db_path: str = os.getenv("DB_PATH", "/app/data/controller.db")
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "100"))

    salad_api_key: str = os.getenv("SALAD_API_KEY", "").strip()
    salad_org: str = os.getenv("SALAD_ORG", "").strip()
    salad_project: str = os.getenv("SALAD_PROJECT", "").strip()
    salad_queue: str = os.getenv("SALAD_QUEUE", "qwen-comfyui").strip()

    r2_endpoint_url: str = os.getenv("R2_ENDPOINT_URL", "").strip()
    r2_bucket: str = os.getenv("R2_BUCKET", "").strip()
    r2_access_key_id: str = os.getenv("R2_ACCESS_KEY_ID", "").strip()
    r2_secret_access_key: str = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
    r2_region: str = os.getenv("R2_REGION", "auto").strip()
    r2_presign_ttl_seconds: int = int(os.getenv("R2_PRESIGN_TTL_SECONDS", "21600"))

    internal_token: str = os.getenv("APP_INTERNAL_TOKEN", "").strip()

    def validate_runtime(self):
        missing = []
        for name, value in [
            ("SALAD_API_KEY", self.salad_api_key),
            ("SALAD_ORG", self.salad_org),
            ("SALAD_PROJECT", self.salad_project),
            ("SALAD_QUEUE", self.salad_queue),
            ("R2_ENDPOINT_URL", self.r2_endpoint_url),
            ("R2_BUCKET", self.r2_bucket),
            ("R2_ACCESS_KEY_ID", self.r2_access_key_id),
            ("R2_SECRET_ACCESS_KEY", self.r2_secret_access_key),
        ]:
            if not value:
                missing.append(name)
        if missing:
            raise RuntimeError("Missing runtime configuration: " + ", ".join(missing))

settings = Settings()

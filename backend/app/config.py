"""Runtime configuration. Deployable values have no in-code defaults.

Docker Compose passes root .env via env_file; salad-deploy.sh sources the same file.
"""
from dataclasses import dataclass
import os


def value(name):
    return os.environ.get(name, "").strip()


def required(name):
    result = value(name)
    if not result:
        raise RuntimeError(f"Missing setting in root .env: {name}")
    return result


def required_int(name):
    try:
        return int(required(name))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


@dataclass(frozen=True)
class Settings:
    app_name: str = required("APP_NAME")
    db_path: str = required("DB_PATH")
    max_upload_mb: int = required_int("MAX_UPLOAD_MB")
    internal_token: str = value("APP_INTERNAL_TOKEN")

    salad_api_key: str = required("SALAD_API_KEY")
    salad_api_base_url: str = required("SALAD_API_BASE_URL").rstrip("/")
    salad_user_agent: str = required("SALAD_USER_AGENT")
    salad_http_timeout_seconds: int = required_int("SALAD_HTTP_TIMEOUT_SECONDS")
    salad_org: str = required("SALAD_ORG")
    salad_project: str = required("SALAD_PROJECT")
    salad_queue_name_value: str = required("SALAD_QUEUE_NAME")
    salad_group_name: str = required("SALAD_CONTAINER_GROUP_NAME")
    salad_priority: str = required("SALAD_PRIORITY").lower()
    salad_gpu_name: str = required("SALAD_GPU_NAME")
    salad_legacy_queue: str = value("SALAD_LEGACY_QUEUE")

    r2_endpoint_url: str = required("R2_ENDPOINT_URL")
    r2_bucket: str = required("R2_BUCKET")
    r2_access_key_id: str = required("R2_ACCESS_KEY_ID")
    r2_secret_access_key: str = required("R2_SECRET_ACCESS_KEY")
    r2_region: str = required("R2_REGION")
    r2_presign_ttl_seconds: int = required_int("R2_PRESIGN_TTL_SECONDS")

    @property
    def salad_default_priority(self):
        return self.salad_priority

    def validate_r2(self):
        # Required fields are checked at object construction.
        if self.max_upload_mb <= 0 or self.r2_presign_ttl_seconds <= 0:
            raise RuntimeError("Upload limit and R2 signed-URL lifetime must be positive")

    def validate_salad(self):
        if self.salad_priority not in ("high", "medium", "low", "batch"):
            raise RuntimeError("Invalid SALAD_PRIORITY in .env")
        if self.salad_http_timeout_seconds <= 0:
            raise RuntimeError("SALAD_HTTP_TIMEOUT_SECONDS must be positive")

    def salad_queue_name(self, priority=None):
        selected = (priority or self.salad_priority).strip().lower()
        if selected != self.salad_priority:
            raise ValueError(f"Only the configured priority {self.salad_priority!r} is enabled")
        return self.salad_queue_name_value

    def validate_runtime(self):
        self.validate_r2()
        self.validate_salad()


settings = Settings()
settings.validate_runtime()

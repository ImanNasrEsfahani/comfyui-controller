import boto3
from botocore.config import Config
from urllib.parse import urlparse
import re
from .config import settings

IMAGE_EXT = re.compile(r"\.(png|jpe?g|webp|gif|avif)$", re.I)


def client():
    settings.validate_r2()
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name=settings.r2_region,
        config=Config(signature_version="s3v4"),
    )


def upload_fileobj(fileobj, key: str, content_type: str | None = None):
    extra = {}
    if content_type:
        extra["ContentType"] = content_type
    kwargs = {"Fileobj": fileobj, "Bucket": settings.r2_bucket, "Key": key}
    if extra:
        kwargs["ExtraArgs"] = extra
    client().upload_fileobj(**kwargs)
    return key


def presign_get(key: str, ttl: int | None = None):
    return client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.r2_bucket, "Key": key},
        ExpiresIn=ttl or settings.r2_presign_ttl_seconds,
    )


def sign_s3_uri(uri: str):
    if not uri.startswith("s3://"):
        return uri
    p = urlparse(uri)
    bucket = p.netloc
    key = p.path.lstrip("/")
    if bucket != settings.r2_bucket:
        return uri
    return presign_get(key)


def sign_s3_values(value):
    if isinstance(value, dict):
        return {k: sign_s3_values(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sign_s3_values(v) for v in value]
    if isinstance(value, str) and value.startswith("s3://"):
        return sign_s3_uri(value)
    return value


def extract_output_keys(value, job_id):
    """Accept only image objects within this job's own R2 output prefix."""
    found = set()
    prefix = f"outputs/{job_id}/"

    def record(bucket, key):
        if bucket == settings.r2_bucket and isinstance(key, str):
            key = key.lstrip("/")
            if key.startswith(prefix) and IMAGE_EXT.search(key.split("?")[0]):
                found.add(key)

    def walk(item):
        if isinstance(item, dict):
            record(item.get("bucket"), item.get("key"))
            for v in item.values():
                walk(v)
        elif isinstance(item, list):
            for v in item:
                walk(v)
        elif isinstance(item, str):
            if item.startswith("s3://"):
                p = urlparse(item)
                record(p.netloc, p.path)
    walk(value)
    return sorted(found)


def job_images(job_id, output=None, *, include_storage=False, limit=12):
    keys = set(extract_output_keys(output, job_id))
    if include_storage:
        # A paginated R2 listing is used on demand, not on every 6-second poll.
        # If ListBucket permission is unavailable, use validated output keys
        # already reported by the remote job instead of losing every preview.
        try:
            c = client()
            pages = c.get_paginator("list_objects_v2").paginate(
                Bucket=settings.r2_bucket, Prefix=f"outputs/{job_id}/",
                PaginationConfig={"MaxItems": 200},
            )
            for page in pages:
                for item in page.get("Contents", []):
                    key = item.get("Key", "")
                    if key.startswith(f"outputs/{job_id}/") and IMAGE_EXT.search(key):
                        keys.add(key)
                        if len(keys) >= limit:
                            break
                if len(keys) >= limit:
                    break
        except Exception:
            if not keys:
                raise
    return [{"key": key, "url": presign_get(key)} for key in sorted(keys)[:limit]]

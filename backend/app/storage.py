import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from urllib.parse import urlparse
import re
import math
from uuid import uuid5, NAMESPACE_URL
from .config import settings

IMAGE_EXT = re.compile(r"\.(png|jpe?g|webp|gif|avif)$", re.I)
MEDIA_EXT = re.compile(r"\.(png|jpe?g|webp|gif|avif|mp4|webm|mov|mkv)$", re.I)


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


def validate_outputs(job_id, attempt_id, output, *, storage_prefix=None):
    """Validate real R2 objects outside SQLite locks; no GPU/provider calls.

    Each new attempt gets its own storage prefix, so a previous attempt's files
    cannot make a new attempt appear successful. Metadata we cannot observe is
    left null. HEAD proves readability to the controller; browser access still
    needs the normal renewed signed URL.
    """
    prefix = storage_prefix or (f"outputs/{job_id}/" + (f"{attempt_id}/" if attempt_id else ""))
    if not prefix.startswith(f"outputs/{job_id}/") or ".." in prefix.split("/"):
        raise ValueError("invalid output prefix")
    keys = set()
    def record(bucket, key):
        if bucket == settings.r2_bucket and isinstance(key, str):
            key = key.lstrip("/")
            if key.startswith(prefix) and ".." not in key.split("/") and MEDIA_EXT.search(key):
                keys.add(key)
    def walk(item):
        if isinstance(item, dict):
            record(item.get("bucket"), item.get("key"))
            for child in item.values(): walk(child)
        elif isinstance(item, list):
            for child in item: walk(child)
        elif isinstance(item, str):
            parsed = urlparse(item)
            if parsed.scheme == "s3":
                record(parsed.netloc, parsed.path)
            elif parsed.scheme == "https" and parsed.hostname == urlparse(settings.r2_endpoint_url).hostname:
                from urllib.parse import unquote
                path = unquote(parsed.path).lstrip("/")
                if path.startswith(settings.r2_bucket + "/"):
                    path = path[len(settings.r2_bucket) + 1:]
                record(settings.r2_bucket, path)
    walk(output)
    c = client()
    if not keys:
        pages = c.get_paginator("list_objects_v2").paginate(Bucket=settings.r2_bucket, Prefix=prefix)
        for page in pages:
            for item in page.get("Contents", []): record(settings.r2_bucket, item.get("Key"))
    assets = []
    from .db import utcnow
    for key in sorted(keys):
        asset = {"asset_id": str(uuid5(NAMESPACE_URL, f"s3://{settings.r2_bucket}/{key}")),
                 "job_id": job_id, "attempt_id": attempt_id, "storage_key": key,
                 "media_type": "video" if re.search(r"\.(mp4|webm|mov|mkv)$", key, re.I) else "image",
                 "mime_type": None, "width": None, "height": None, "size_bytes": None,
                 "duration_seconds": None, "frame_rate": None, "status": "unavailable",
                 "verified_at": None, "error_code": None}
        asset["created_at"] = utcnow()
        try:
            head = c.head_object(Bucket=settings.r2_bucket, Key=key)
            size = head.get("ContentLength")
            if not isinstance(size, int) or size <= 0:
                raise ValueError("empty output")
            mime = head.get("ContentType")
            if mime and mime != "application/octet-stream" and not mime.startswith(asset["media_type"] + "/"):
                raise ValueError("unexpected output content type")
            asset.update(mime_type=head.get("ContentType"), size_bytes=size, status="available", verified_at=utcnow())
            metadata = head.get("Metadata") or {}
            for field in ("width", "height", "duration_seconds", "frame_rate"):
                try:
                    value = int(metadata[field]) if field in ("width", "height") else float(metadata[field])
                    if value > 0 and math.isfinite(value): asset[field] = value
                except (KeyError, TypeError, ValueError, OverflowError):
                    pass
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0) >= 500 or exc.response.get("Error", {}).get("Code") in {"SlowDown", "RequestTimeout"}:
                raise
            asset["error_code"] = "output_unavailable:" + type(exc).__name__
        except BotoCoreError:
            raise
        except (ValueError, FileNotFoundError, PermissionError) as exc:
            asset["error_code"] = "output_unavailable:" + type(exc).__name__
        assets.append(asset)
    return assets


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

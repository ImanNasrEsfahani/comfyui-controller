import boto3
from botocore.config import Config
from urllib.parse import urlparse
from .config import settings

def client():
    settings.validate_runtime()
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

from io import BytesIO

from minio import Minio
from minio.error import S3Error

from ontoexplorer.config import get_settings

_client: Minio | None = None
_public_client: Minio | None = None


def get_minio_client() -> Minio:
    global _client
    if _client is None:
        s = get_settings()
        _client = Minio(
            s.minio_endpoint,
            access_key=s.minio_access_key,
            secret_key=s.minio_secret_key,
            secure=s.minio_secure,
        )
    return _client


def _get_public_minio_client() -> Minio:
    """Client used only for presigned URL generation.

    Uses minio_public_endpoint when set so generated URLs are reachable by
    browsers. Falls back to the internal client when unset (local dev).
    """
    global _public_client
    if _public_client is None:
        s = get_settings()
        endpoint = s.minio_public_endpoint or s.minio_endpoint
        secure = s.minio_public_secure if s.minio_public_endpoint else s.minio_secure
        _public_client = Minio(
            endpoint,
            access_key=s.minio_access_key,
            secret_key=s.minio_secret_key,
            secure=secure,
        )
    return _public_client


def ensure_bucket(bucket: str) -> None:
    client = get_minio_client()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def upload_bytes(bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    ensure_bucket(bucket)
    client = get_minio_client()
    client.put_object(bucket, key, BytesIO(data), length=len(data), content_type=content_type)


def download_bytes(bucket: str, key: str) -> bytes:
    client = get_minio_client()
    response = client.get_object(bucket, key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def presigned_get_url(bucket: str, key: str, expires_seconds: int = 3600) -> str:
    from datetime import timedelta
    return _get_public_minio_client().presigned_get_object(bucket, key, expires=timedelta(seconds=expires_seconds))


def object_exists(bucket: str, key: str) -> bool:
    client = get_minio_client()
    try:
        client.stat_object(bucket, key)
        return True
    except S3Error as e:
        if e.code == "NoSuchKey":
            return False
        raise

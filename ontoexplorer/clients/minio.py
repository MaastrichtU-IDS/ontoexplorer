from io import BytesIO

from minio import Minio
from minio.error import S3Error

from ontoexplorer.config import get_settings

_client: Minio | None = None


def get_minio_client() -> Minio:
    global _client
    if _client is None:
        s = get_settings()
        _client = Minio(
            s.minio_endpoint,
            access_key=s.minio_access_key,
            secret_key=s.minio_secret_key,
            secure=s.minio_secure,
            region=s.minio_region,
        )
    return _client


def ensure_bucket(bucket: str) -> None:
    client = get_minio_client()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def upload_bytes(bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    ensure_bucket(bucket)
    client = get_minio_client()
    client.put_object(bucket, key, BytesIO(data), length=len(data), content_type=content_type)


# 16 MiB multipart chunks: bounds peak memory during a streamed upload to one
# part at a time, regardless of total file size.
_STREAM_PART_SIZE = 16 * 1024 * 1024


def upload_stream(
    bucket: str,
    key: str,
    fileobj,
    length: int = -1,
    content_type: str = "application/octet-stream",
) -> None:
    """Stream a file-like object straight to MinIO without buffering it all in memory.

    Pass length=-1 when the size is unknown; MinIO then does a multipart upload,
    reading _STREAM_PART_SIZE bytes at a time. Caller should seek(0) first.
    """
    ensure_bucket(bucket)
    client = get_minio_client()
    client.put_object(
        bucket, key, fileobj,
        length=length,
        part_size=_STREAM_PART_SIZE if length < 0 else 0,
        content_type=content_type,
    )


def remove_object(bucket: str, key: str) -> None:
    """Delete an object. Silently ignores a missing object or bucket."""
    client = get_minio_client()
    try:
        client.remove_object(bucket, key)
    except S3Error as e:
        if e.code in ("NoSuchKey", "NoSuchBucket"):
            return
        raise


# Download chunk size. Smaller than the 16 MiB upload part above: this bounds
# the per-request footprint of a download, and several can be in flight at once.
_DOWNLOAD_CHUNK_SIZE = 1024 * 1024


def stream_object(bucket: str, key: str, chunk_size: int = _DOWNLOAD_CHUNK_SIZE):
    """Yield an object's bytes in chunks, releasing the connection when done.

    The counterpart to upload_stream. Reading a whole object into memory to
    serve it costs twice its size (the bytes, then the response copy) against
    the api container's memory limit, per concurrent request -- fine for the
    tens of MB stored today, not for the multi-GB uploads this accepts.
    """
    client = get_minio_client()
    response = client.get_object(bucket, key)
    try:
        yield from response.stream(chunk_size)
    finally:
        response.close()
        response.release_conn()


def object_size(bucket: str, key: str) -> int | None:
    """Object size in bytes, or None if it cannot be determined."""
    try:
        return get_minio_client().stat_object(bucket, key).size
    except Exception:
        return None


def download_bytes(bucket: str, key: str) -> bytes:
    client = get_minio_client()
    response = client.get_object(bucket, key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def object_exists(bucket: str, key: str) -> bool:
    client = get_minio_client()
    try:
        client.stat_object(bucket, key)
        return True
    except S3Error as e:
        # A missing object OR a not-yet-created bucket both mean "not present".
        # NoSuchBucket matters on a fresh deployment: the imports bucket is only
        # created lazily by the first store_import(), but import_exists() runs
        # first — so without this the very first import resolution always throws.
        if e.code in ("NoSuchKey", "NoSuchBucket"):
            return False
        raise

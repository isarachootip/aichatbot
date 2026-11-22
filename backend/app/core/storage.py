"""S3-compatible object storage interface for MinIO and production S3 buckets."""

import asyncio
from typing import Protocol, runtime_checkable

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from app.core.config import Settings


@runtime_checkable
class ObjectStorage(Protocol):
    """Async byte storage boundary for uploaded knowledge-base documents."""

    async def ensure_bucket(self) -> None:
        """Create the configured storage bucket if it does not already exist."""
        ...

    async def upload_bytes(self, key: str, data: bytes, content_type: str) -> None:
        """Store raw bytes under the given object key."""
        ...

    async def download_bytes(self, key: str) -> bytes:
        """Fetch raw bytes for the given object key."""
        ...


class S3ObjectStorage:
    """Async wrapper over boto3 S3 client compatible with MinIO and AWS S3."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region_name: str = "us-east-1",
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region_name,
            config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "S3ObjectStorage":
        """Build an S3ObjectStorage client from application settings."""
        return cls(
            endpoint_url=settings.s3_endpoint_url,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            bucket=settings.s3_bucket,
        )

    def _ensure_bucket_sync(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            if error_code in {"404", "NoSuchBucket", "NotFound"}:
                self._client.create_bucket(Bucket=self._bucket)
            else:
                raise

    def _upload_sync(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    def _download_sync(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        body = response["Body"]
        raw: bytes = body.read()
        return raw

    async def ensure_bucket(self) -> None:
        """Ensure the S3/MinIO bucket exists."""
        await asyncio.to_thread(self._ensure_bucket_sync)

    async def upload_bytes(self, key: str, data: bytes, content_type: str) -> None:
        """Upload raw file bytes into the configured bucket."""
        await asyncio.to_thread(self._upload_sync, key, data, content_type)

    async def download_bytes(self, key: str) -> bytes:
        """Download raw file bytes from the configured bucket."""
        return await asyncio.to_thread(self._download_sync, key)


class InMemoryStorage:
    """Deterministic in-memory object store for fast unit and integration tests."""

    def __init__(self) -> None:
        self._objects: dict[str, tuple[bytes, str]] = {}

    async def ensure_bucket(self) -> None:
        """No-op for in-memory storage."""

    async def upload_bytes(self, key: str, data: bytes, content_type: str) -> None:
        """Store raw bytes in memory."""
        self._objects[key] = (data, content_type)

    async def download_bytes(self, key: str) -> bytes:
        """Retrieve raw bytes from memory or raise KeyError."""
        if key not in self._objects:
            raise FileNotFoundError(f"Object not found in storage: {key}")
        return self._objects[key][0]

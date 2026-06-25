import asyncio
from functools import partial

import boto3
from botocore.config import Config

from src.config import settings


def _get_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def _upload_sync(key: str, data: bytes, content_type: str) -> None:
    _get_client().put_object(
        Bucket=settings.r2_bucket_name,
        Key=key,
        Body=data,
        ContentType=content_type,
    )


def _download_sync(key: str) -> bytes:
    response = _get_client().get_object(Bucket=settings.r2_bucket_name, Key=key)
    return response["Body"].read()


def _delete_sync(key: str) -> None:
    _get_client().delete_object(Bucket=settings.r2_bucket_name, Key=key)


async def upload_file(key: str, data: bytes, content_type: str = "application/pdf") -> str:
    await asyncio.to_thread(partial(_upload_sync, key, data, content_type))
    return key


async def download_file(key: str) -> bytes:
    return await asyncio.to_thread(partial(_download_sync, key))


async def delete_file(key: str) -> None:
    await asyncio.to_thread(partial(_delete_sync, key))


def download_file_sync(key: str) -> bytes:
    return _download_sync(key)


def upload_file_sync(key: str, data: bytes, content_type: str = "application/pdf") -> str:
    _upload_sync(key, data, content_type)
    return key


def _presigned_url_sync(key: str, expires_in: int) -> str:
    return _get_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.r2_bucket_name, "Key": key},
        ExpiresIn=expires_in,
    )


async def generate_presigned_url(key: str, expires_in: int = 3600) -> str:
    """Returns a time-limited URL to download a private R2 object."""
    return await asyncio.to_thread(partial(_presigned_url_sync, key, expires_in))

"""MinIO object storage for the pipeline.

MinIO speaks the S3 API, so we use boto3's S3 client pointed at the local MinIO
endpoint. This wrapper handles the few operations we need: make sure a bucket
exists, upload bytes, and read them back.
"""

from __future__ import annotations

import hashlib

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


def compute_hash(data: bytes) -> str:
    # This is the file_hash we store and compare
    # between runs to tell whether a document changed.
    return hashlib.sha256(data).hexdigest()


class MinioStore:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, region: str):
        # endpoint_url points boto3 at MinIO instead of real AWS S3. The API
        # calls are identical, which is the whole point of an S3-compatible store.
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(signature_version="s3v4"),
        )

    def ensure_bucket(self, bucket: str) -> None:
        # head_bucket succeeds if the bucket exists; if not, create it. Idempotent
        # so it is safe to call at the start of every run.
        try:
            self.client.head_bucket(Bucket=bucket)
        except ClientError:
            self.client.create_bucket(Bucket=bucket)

    def upload(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)

    def download(self, bucket: str, key: str) -> bytes:
        # Read an object's bytes back out of the store.
        return self.client.get_object(Bucket=bucket, Key=key)["Body"].read()

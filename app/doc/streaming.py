"""Streaming upload pipeline: sha256 + size accumulation, no full buffering.

The file is read in 1 MB chunks.  While reading we
* update the sha256 digest,
* accumulate the byte counter (the ``Content-Length`` header is NEVER
  trusted - the client may lie about it),
* push the bytes into an S3 multipart upload, so the payload travels to the
  object store while it is being hashed.

As soon as the accumulated size exceeds the limit the multipart upload is
aborted, which removes every part that was already written: the bucket
keeps no half object and no pending multipart upload.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable

from ..errors import StorageError

CHUNK_SIZE = 1024 * 1024
S3_PART_SIZE = 8 * 1024 * 1024


class UploadTooLargeError(Exception):
    """Raised when the streamed size exceeds the configured limit."""

    def __init__(self, size: int, limit: int) -> None:
        super().__init__(f"uploaded size {size} exceeds the limit of {limit} bytes")
        self.size = size
        self.limit = limit


@dataclass
class StreamOutcome:
    sha256: str
    size: int
    key: str
    writer: "MultipartWriter"


class MultipartWriter:
    """Writes a streamed payload into an S3 multipart upload."""

    def __init__(self, adapter: Any, key: str, content_type: str, part_size: int = S3_PART_SIZE) -> None:
        self.adapter = adapter
        self.key = key
        self.content_type = content_type
        self.part_size = part_size
        self._buffer = bytearray()
        self._parts: list[dict[str, Any]] = []
        self._part_number = 1
        self._upload_id: str | None = None
        self._completed = False

    def _ensure_upload(self) -> str:
        if self._upload_id is None:
            self._upload_id = self.adapter.client.create_multipart_upload(
                Bucket=self.adapter.bucket,
                Key=self.key,
                ContentType=self.content_type,
            )["UploadId"]
        return self._upload_id

    @property
    def upload_id(self) -> str | None:
        return self._upload_id

    def write(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._buffer.extend(chunk)
        while len(self._buffer) >= self.part_size:
            self._flush_part(bytes(self._buffer[: self.part_size]))
            del self._buffer[: self.part_size]

    def _flush_part(self, block: bytes) -> None:
        upload_id = self._ensure_upload()
        etag = self.adapter.client.upload_part(
            Bucket=self.adapter.bucket,
            Key=self.key,
            UploadId=upload_id,
            PartNumber=self._part_number,
            Body=block,
        )["ETag"]
        self._parts.append({"ETag": etag, "PartNumber": self._part_number})
        self._part_number += 1

    def finish(self) -> str:
        """Complete the multipart upload -> the object becomes visible."""
        if self._buffer:
            self._flush_part(bytes(self._buffer))
            self._buffer.clear()
        upload_id = self._ensure_upload()
        result = self.adapter.client.complete_multipart_upload(
            Bucket=self.adapter.bucket,
            Key=self.key,
            UploadId=upload_id,
            MultipartUpload={"Parts": self._parts},
        )
        self._completed = True
        self._upload_id = None
        return result.get("ETag", "")

    def abort(self) -> None:
        """Abort the multipart upload - every written part disappears."""
        if self._upload_id is None:
            return
        self.adapter.abort_multipart(self.key, self._upload_id)
        self._upload_id = None
        self._parts = []
        self._buffer.clear()


def stream_to_object(
    *,
    adapter: Any,
    key: str,
    content_type: str,
    chunks: Iterable[bytes],
    max_size: int,
    chunk_size: int = CHUNK_SIZE,
    on_first_chunk: Any = None,
) -> StreamOutcome:
    """Stream ``chunks`` into ``key`` while hashing and counting bytes.

    ``on_first_chunk`` is an optional callback that receives the first chunk
    (used for the magic number check) and may raise - in that case the
    multipart upload is aborted and nothing is left behind.
    """
    digest = hashlib.sha256()
    size = 0
    writer = MultipartWriter(adapter, key, content_type)
    first = True
    try:
        for chunk in chunks:
            if not chunk:
                continue
            if first:
                first = False
                if on_first_chunk is not None:
                    on_first_chunk(chunk)
            size += len(chunk)
            if size > max_size:
                writer.abort()
                raise UploadTooLargeError(size=size, limit=max_size)
            digest.update(chunk)
            writer.write(chunk)
        if first and on_first_chunk is not None:
            # empty file: still let the caller run its checks
            on_first_chunk(b"")
        return StreamOutcome(sha256=digest.hexdigest(), size=size, key=key, writer=writer)
    except UploadTooLargeError:
        raise
    except Exception as exc:
        writer.abort()
        raise StorageError(f"upload stream failed for {key}: {exc}") from exc

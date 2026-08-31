"""Content-addressed local blob store, matching the BlobStore protocol PIPELINE.md
specifies (§ "Storage interface") — LocalBlobStore for the demo, S3BlobStore for
production, identical key layout so switching is a config change, not a code change.

Originals are immutable from the moment they're written: `put(..., immutable=True)`
refuses to overwrite an existing key. Every derived artifact (page rasters) lives
under `derived/{pipeline_version}/{sha256}/...`, never touching the original.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol


class BlobStore(Protocol):
    def put(self, key: str, data: bytes, *, immutable: bool = True) -> str: ...
    def get(self, key: str) -> bytes: ...
    def uri(self, key: str) -> str: ...
    def exists(self, key: str) -> bool: ...


class LocalBlobStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / key

    def put(self, key: str, data: bytes, *, immutable: bool = True) -> str:
        path = self._path(key)
        if immutable and path.exists():
            raise FileExistsError(f"refusing to overwrite immutable key {key}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return self.uri(key)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def uri(self, key: str) -> str:
        return f"file://{self._path(key)}"

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def original_key(sha256: str) -> str:
    """documents/{sha256[0:2]}/{sha256} — per PIPELINE.md § S0."""
    return f"documents/{sha256[:2]}/{sha256}"


def raster_key(pipeline_version: str, sha256: str, page_no: int) -> str:
    return f"derived/{pipeline_version}/{sha256}/page-{page_no:03d}.png"


def verify_original(store: BlobStore, sha256: str) -> bool:
    """Re-verify SHA256(fetched bytes) == documents.sha256 before ever serving a
    document as evidence — PIPELINE.md § S0. The stored URI is a hint about where to
    look, not the authority on what the bytes are; only the hash is."""
    data = store.get(original_key(sha256))
    return sha256_hex(data) == sha256

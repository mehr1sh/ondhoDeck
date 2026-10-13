"""Private object storage.

* `SupabaseStorage` - production: private Supabase Storage bucket accessed only with the
  server-side service-role key; downloads use short-lived signed URLs.
* `LocalStorage` - development and tests only (refused in preview/production by config).
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

from .config import Settings, get_settings


class StorageError(RuntimeError):
    pass


class Storage(Protocol):
    def put(self, path: str, data: bytes, content_type: str) -> None: ...
    def get(self, path: str) -> bytes: ...
    def delete(self, paths: list[str]) -> None: ...
    def signed_url(self, path: str, ttl_seconds: int, download_name: str) -> str: ...


def safe_filename(name: str, max_len: int = 120) -> str:
    """Strip paths, control and special characters; keep a readable ASCII name ending in .pdf."""
    name = unicodedata.normalize("NFKD", Path(name.replace("\\", "/")).name).encode("ascii", "ignore").decode()
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" ._-")
    stem = re.sub(r"\.pdf$", "", name, flags=re.I)[: max_len - 4] or "document"
    return f"{stem}.pdf"


class SupabaseStorage:
    def __init__(self, settings: Settings):
        self.base = settings.supabase_url.rstrip("/") + "/storage/v1"
        self.bucket = settings.storage_bucket
        self.headers = {"Authorization": f"Bearer {settings.supabase_service_role_key}",
                        "apikey": settings.supabase_service_role_key}

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=60, headers=self.headers)

    def put(self, path: str, data: bytes, content_type: str) -> None:
        with self._client() as c:
            r = c.post(f"{self.base}/object/{self.bucket}/{quote(path)}", content=data,
                       headers={"Content-Type": content_type, "x-upsert": "false"})
        if r.status_code not in (200, 201):
            raise StorageError(f"upload failed with status {r.status_code}")

    def get(self, path: str) -> bytes:
        with self._client() as c:
            r = c.get(f"{self.base}/object/authenticated/{self.bucket}/{quote(path)}")
        if r.status_code != 200:
            raise StorageError(f"download failed with status {r.status_code}")
        return r.content

    def delete(self, paths: list[str]) -> None:
        if not paths:
            return
        with self._client() as c:
            r = c.request("DELETE", f"{self.base}/object/{self.bucket}", json={"prefixes": paths})
        if r.status_code not in (200, 204):
            raise StorageError(f"delete failed with status {r.status_code}")

    def signed_url(self, path: str, ttl_seconds: int, download_name: str) -> str:
        with self._client() as c:
            r = c.post(f"{self.base}/object/sign/{self.bucket}/{quote(path)}", json={"expiresIn": ttl_seconds})
        if r.status_code != 200:
            raise StorageError(f"signing failed with status {r.status_code}")
        signed = r.json().get("signedURL") or r.json().get("signedUrl")
        sep = "&" if "?" in signed else "?"
        return f"{self.base}{signed}{sep}download={quote(download_name)}"


class LocalStorage:
    """Filesystem storage for development/tests. Signed URLs point at the API's local download route."""

    def __init__(self, settings: Settings):
        self.root = Path(settings.local_storage_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.secret = (settings.supabase_jwt_secret or "local-dev").encode()

    def _path(self, path: str) -> Path:
        p = (self.root / path).resolve()
        if self.root not in p.parents:
            raise StorageError("invalid storage path")
        return p

    def put(self, path: str, data: bytes, content_type: str) -> None:
        p = self._path(path)
        if p.exists():
            raise StorageError("object already exists")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, path: str) -> bytes:
        p = self._path(path)
        if not p.exists():
            raise StorageError("object not found")
        return p.read_bytes()

    def delete(self, paths: list[str]) -> None:
        for path in paths:
            self._path(path).unlink(missing_ok=True)

    def sign(self, path: str, expires: int) -> str:
        return hmac.new(self.secret, f"{path}:{expires}".encode(), hashlib.sha256).hexdigest()

    def signed_url(self, path: str, ttl_seconds: int, download_name: str) -> str:
        expires = int(time.time()) + ttl_seconds
        return (f"/api/v1/local-storage/{quote(path)}?expires={expires}&sig={self.sign(path, expires)}"
                f"&download={quote(download_name)}")

    def verify(self, path: str, expires: int, sig: str) -> bool:
        return expires >= time.time() and hmac.compare_digest(self.sign(path, expires), sig)


@lru_cache
def get_storage() -> Storage:
    settings = get_settings()
    return SupabaseStorage(settings) if settings.storage_backend == "supabase" else LocalStorage(settings)

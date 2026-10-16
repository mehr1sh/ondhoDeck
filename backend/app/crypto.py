"""Encryption at rest for user-supplied provider API keys (BYOK).

Uses Fernet (AES-128-CBC + HMAC-SHA256, from the `cryptography` package) via MultiFernet so keys can be
rotated: the first key in CREDENTIALS_ENCRYPTION_KEYS encrypts, every listed key can decrypt, and
`rotate()` re-encrypts with the first key. Each ciphertext embeds the owning user id and provider; a
ciphertext moved to another row fails to decrypt instead of being used for someone else.

When no encryption key is configured, storing credentials is disabled - plaintext keys are never stored.
Generate a key with:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

import json
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from .config import get_settings


class CredentialStorageUnavailable(RuntimeError):
    pass


class CredentialDecryptionError(RuntimeError):
    pass


class CredentialCipher:
    def __init__(self, keys: list[str]):
        if not keys:
            raise CredentialStorageUnavailable("no encryption keys configured")
        try:
            self._fernet = MultiFernet([Fernet(k.encode()) for k in keys])
        except (ValueError, TypeError) as exc:
            raise CredentialStorageUnavailable("invalid credential encryption key") from exc

    def encrypt(self, secret: str, *, owner: str, provider: str) -> str:
        payload = json.dumps({"k": secret, "o": owner, "p": provider}, separators=(",", ":"))
        return self._fernet.encrypt(payload.encode()).decode()

    def decrypt(self, token: str, *, owner: str, provider: str) -> str:
        try:
            payload = json.loads(self._fernet.decrypt(token.encode()))
        except (InvalidToken, ValueError) as exc:
            raise CredentialDecryptionError("stored credential could not be decrypted") from exc
        if payload.get("o") != owner or payload.get("p") != provider:
            raise CredentialDecryptionError("stored credential does not belong to this owner/provider")
        return payload["k"]

    def rotate(self, token: str) -> str:
        return self._fernet.rotate(token.encode()).decode()


@lru_cache
def _cipher_for(keys: str) -> CredentialCipher:
    return CredentialCipher([k.strip() for k in keys.split(",") if k.strip()])


def get_cipher() -> CredentialCipher:
    keys = get_settings().credentials_encryption_keys
    if not keys.strip():
        raise CredentialStorageUnavailable("credential storage is not configured on this server")
    return _cipher_for(keys)


def key_hint(secret: str) -> str:
    """Masked indicator for display: last four characters only."""
    return "…" + secret[-4:] if len(secret) >= 8 else "…"

"""Symmetric encryption for provider API keys at rest (EPIC-023).

Provider secrets live in the database (EPIC B), so they must be encrypted with a
project-level key supplied out-of-band via ``LLM_ENCRYPTION_KEYS`` (env/Vault).
We use Fernet (authenticated AES-128-CBC + HMAC) wrapped in ``MultiFernet`` so
key rotation is a single pass:

    1. Generate a new key, prepend it to ``LLM_ENCRYPTION_KEYS`` (newest first).
    2. Re-encrypt every stored secret with :meth:`FernetCipher.rotate` — decrypt
       succeeds with any held key, re-encrypt always uses the newest.
    3. Once every row carries the new ``key_version``, drop the old key.

The cipher knows nothing about storage; the row-by-row rotation loop lives in the
DB layer that owns the secrets.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

import src.config
from src.llm.base.errors import LLMConfigError
from src.llm.base.types.core import Encrypted

# Bound from the bare published root (config publishes no named symbols).
settings = src.config.settings


@runtime_checkable
class SecretCipher(Protocol):
    """Contract for encrypting/decrypting provider secrets."""

    @property
    def current_version(self) -> int:
        """Version stamped onto freshly-encrypted values (bumps on rotation)."""
        ...

    def encrypt(self, plaintext: str) -> Encrypted: ...

    def decrypt(self, value: Encrypted) -> str: ...

    def rotate(self, value: Encrypted) -> Encrypted:
        """Re-encrypt an existing value with the newest key."""
        ...


class FernetCipher:
    """``MultiFernet``-backed :class:`SecretCipher`.

    Keys are ordered newest-first: index 0 encrypts, all keys are tried on
    decrypt. ``current_version`` is a *stable fingerprint of the encrypting key*
    (not the key count): rotating to a new key changes the stamp, while dropping
    a retired key never changes a surviving key's stamp. So a row needs
    re-stamping iff ``row.key_version != cipher.current_version`` — a check that
    stays correct across the whole rotation lifecycle (the key-count approach
    was non-monotonic: dropping the old key lowered the version again).
    """

    def __init__(self, keys: Sequence[str]) -> None:
        if not keys:
            raise LLMConfigError("FernetCipher requires at least one key")
        try:
            fernets = [Fernet(key.encode("ascii")) for key in keys]
        except (ValueError, TypeError) as exc:
            raise LLMConfigError("Invalid Fernet key in LLM_ENCRYPTION_KEYS (need urlsafe base64, 32 bytes)") from exc
        self._multi = MultiFernet(fernets)
        self._version = _key_fingerprint(keys[0])

    @property
    def current_version(self) -> int:
        return self._version

    def encrypt(self, plaintext: str) -> Encrypted:
        token = self._multi.encrypt(plaintext.encode("utf-8"))
        return Encrypted(ciphertext=token.decode("ascii"), key_version=self._version)

    def decrypt(self, value: Encrypted) -> str:
        try:
            return self._multi.decrypt(value.ciphertext.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise LLMConfigError(
                "Could not decrypt provider secret — the encrypting key is no longer in "
                "LLM_ENCRYPTION_KEYS (rotated out) or the value is corrupt."
            ) from exc

    def rotate(self, value: Encrypted) -> Encrypted:
        """Re-encrypt ``value`` under the newest key (single-pass rotation step)."""
        try:
            token = self._multi.rotate(value.ciphertext.encode("ascii"))
        except InvalidToken as exc:
            raise LLMConfigError("Could not rotate provider secret — encrypting key missing or value corrupt.") from exc
        return Encrypted(ciphertext=token.decode("ascii"), key_version=self._version)


def _key_fingerprint(key: str) -> int:
    """A stable, non-reversible 32-bit id for a Fernet key.

    The first 4 bytes of SHA-256 over the key. It identifies *which* key sealed a
    value without revealing the key, and is independent of how many keys are
    configured, so it survives dropping retired keys after a rotation pass.
    """
    digest = hashlib.sha256(key.encode("ascii")).digest()
    return int.from_bytes(digest[:4], "big")


def build_cipher() -> FernetCipher:
    """Construct the project cipher from ``LLM_ENCRYPTION_KEYS``.

    Raises :class:`LLMConfigError` when no key is configured — callers that store
    provider secrets must surface this as "DB-backed provider config unavailable".
    """
    keys = settings.llm_encryption_key_list
    if not keys:
        raise LLMConfigError(
            "LLM_ENCRYPTION_KEYS is not set; DB-backed provider secrets cannot be encrypted. "
            "Set a Fernet key (urlsafe base64, 32 bytes) via env/Vault."
        )
    return FernetCipher(keys)

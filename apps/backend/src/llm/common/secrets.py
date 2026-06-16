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

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from src.config import settings
from src.llm.common.errors import LLMConfigError
from src.llm.common.types import Encrypted


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
    decrypt. ``current_version`` is the key count, so prepending a rotation key
    bumps it and lets callers detect not-yet-rotated rows.
    """

    def __init__(self, keys: Sequence[str]) -> None:
        if not keys:
            raise LLMConfigError("FernetCipher requires at least one key")
        try:
            fernets = [Fernet(key.encode("ascii")) for key in keys]
        except (ValueError, TypeError) as exc:
            raise LLMConfigError("Invalid Fernet key in LLM_ENCRYPTION_KEYS (need urlsafe base64, 32 bytes)") from exc
        self._multi = MultiFernet(fernets)
        self._version = len(fernets)

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

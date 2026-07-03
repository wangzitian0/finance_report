"""Unit tests for provider-secret encryption + rotation (EPIC-023 AC-llm.1.2-.4)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from src.config import settings
from src.llm.base import FernetCipher, LLMConfigError, build_cipher


def _key() -> str:
    """A fresh Fernet key as the str form FernetCipher expects."""
    return Fernet.generate_key().decode("ascii")


def test_AC23_1_2_round_trips_a_provider_secret_without_storing_plaintext():
    """AC-llm.1.2: encrypt -> decrypt recovers the secret; ciphertext is not the plaintext."""
    cipher = FernetCipher([_key()])
    secret = "sk-super-secret-provider-key"

    sealed = cipher.encrypt(secret)

    assert sealed.ciphertext != secret
    assert secret not in sealed.ciphertext
    assert sealed.key_version == cipher.current_version
    assert cipher.decrypt(sealed) == secret


def test_AC23_1_3_rotation_is_single_pass_old_ciphertext_still_decrypts():
    """AC-llm.1.3: after prepending a new key, an old secret still decrypts and re-stamps.

    The version stamp is a stable fingerprint of the encrypting key, so "needs
    re-stamping" is `row.key_version != cipher.current_version` and stays correct
    even after the retired key is dropped.
    """
    old_key, new_key = _key(), _key()

    old_cipher = FernetCipher([old_key])
    sealed = old_cipher.encrypt("provider-key")
    assert sealed.key_version == old_cipher.current_version

    # Rotation step 1: prepend the new key (newest first); both keys held.
    rotating = FernetCipher([new_key, old_key])
    assert rotating.current_version != old_cipher.current_version  # new encrypting key -> new stamp
    assert rotating.decrypt(sealed) == "provider-key"
    # A not-yet-rotated row is detectable: its stamp != the current encrypting key.
    assert sealed.key_version != rotating.current_version

    # Rotation step 2: re-encrypt under the newest key and re-stamp the version.
    rotated = rotating.rotate(sealed)
    assert rotated.key_version == rotating.current_version
    assert rotating.decrypt(rotated) == "provider-key"

    # Rotation step 3: dropping the retired key does NOT change the surviving
    # key's fingerprint, so already-rotated rows stay marked done.
    new_only = FernetCipher([new_key])
    assert new_only.current_version == rotating.current_version
    assert new_only.decrypt(rotated) == "provider-key"
    # ...and the not-yet-rotated ciphertext fails closed under the new key alone.
    with pytest.raises(LLMConfigError):
        new_only.decrypt(sealed)


def test_AC23_1_3_rotate_fails_closed_on_a_corrupt_value():
    """AC-llm.1.3: rotating a value no key can decrypt fails closed, not silently."""
    from src.llm.base import Encrypted

    cipher = FernetCipher([_key()])
    with pytest.raises(LLMConfigError):
        cipher.rotate(Encrypted(ciphertext="not-a-valid-token", key_version=1))


def test_AC23_1_4_build_cipher_fails_closed_without_a_key(monkeypatch):
    """AC-llm.1.4: no LLM_ENCRYPTION_KEYS -> build_cipher raises (DB secrets fail closed)."""
    monkeypatch.setattr(settings, "llm_encryption_key_list", [], raising=False)
    with pytest.raises(LLMConfigError):
        build_cipher()


def test_AC23_1_4_build_cipher_uses_configured_keys(monkeypatch):
    """AC-llm.1.4: build_cipher constructs a working cipher from configured keys."""
    monkeypatch.setattr(settings, "llm_encryption_key_list", [_key()], raising=False)
    cipher = build_cipher()
    assert cipher.decrypt(cipher.encrypt("x")) == "x"


def test_AC23_1_4_fernet_cipher_rejects_empty_and_malformed_keys():
    """AC-llm.1.4: an empty key list or a non-Fernet key is a config error, not a crash."""
    with pytest.raises(LLMConfigError):
        FernetCipher([])
    with pytest.raises(LLMConfigError):
        FernetCipher(["this-is-not-a-valid-fernet-key"])

"""Unit tests for provider-secret encryption + rotation (EPIC-023 AC23.1.2-.4)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from src.config import settings
from src.llm.common import FernetCipher, LLMConfigError, build_cipher


def _key() -> str:
    """A fresh Fernet key as the str form FernetCipher expects."""
    return Fernet.generate_key().decode("ascii")


def test_AC23_1_2_round_trips_a_provider_secret_without_storing_plaintext():
    """AC23.1.2: encrypt -> decrypt recovers the secret; ciphertext is not the plaintext."""
    cipher = FernetCipher([_key()])
    secret = "sk-super-secret-provider-key"

    sealed = cipher.encrypt(secret)

    assert sealed.ciphertext != secret
    assert secret not in sealed.ciphertext
    assert sealed.key_version == 1
    assert cipher.decrypt(sealed) == secret


def test_AC23_1_3_rotation_is_single_pass_old_ciphertext_still_decrypts():
    """AC23.1.3: after prepending a new key, an old secret still decrypts and re-stamps."""
    old_key, new_key = _key(), _key()

    old_cipher = FernetCipher([old_key])
    sealed = old_cipher.encrypt("provider-key")
    assert sealed.key_version == 1

    # Rotation step 1: prepend the new key (newest first); both keys held.
    rotating = FernetCipher([new_key, old_key])
    assert rotating.current_version == 2
    # Old ciphertext keeps decrypting while both keys are present.
    assert rotating.decrypt(sealed) == "provider-key"

    # Rotation step 2: re-encrypt under the newest key and re-stamp the version.
    rotated = rotating.rotate(sealed)
    assert rotated.key_version == 2
    assert rotating.decrypt(rotated) == "provider-key"

    # Rotation step 3: once every row is re-stamped, the old key can be dropped.
    new_only = FernetCipher([new_key])
    assert new_only.decrypt(rotated) == "provider-key"
    # ...and the not-yet-rotated ciphertext fails closed under the new key alone.
    with pytest.raises(LLMConfigError):
        new_only.decrypt(sealed)


def test_AC23_1_4_build_cipher_fails_closed_without_a_key(monkeypatch):
    """AC23.1.4: no LLM_ENCRYPTION_KEYS -> build_cipher raises (DB secrets fail closed)."""
    monkeypatch.setattr(settings, "llm_encryption_key_list", [], raising=False)
    with pytest.raises(LLMConfigError):
        build_cipher()


def test_AC23_1_4_build_cipher_uses_configured_keys(monkeypatch):
    """AC23.1.4: build_cipher constructs a working cipher from configured keys."""
    monkeypatch.setattr(settings, "llm_encryption_key_list", [_key()], raising=False)
    cipher = build_cipher()
    assert cipher.decrypt(cipher.encrypt("x")) == "x"


def test_AC23_1_4_fernet_cipher_rejects_empty_and_malformed_keys():
    """AC23.1.4: an empty key list or a non-Fernet key is a config error, not a crash."""
    with pytest.raises(LLMConfigError):
        FernetCipher([])
    with pytest.raises(LLMConfigError):
        FernetCipher(["this-is-not-a-valid-fernet-key"])

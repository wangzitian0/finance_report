from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from src.config import settings
from src.llm.base import Encrypted, FernetCipher, LLMConfigError, build_cipher

_key = lambda: Fernet.generate_key().decode("ascii")


def test_AC23_1_cipher_round_trip_rotation_and_build(monkeypatch) -> None:
    old_key, new_key, secret = _key(), _key(), "sk-super-secret-provider-key"
    old_cipher, rotating, new_only = FernetCipher([old_key]), FernetCipher([new_key, old_key]), FernetCipher([new_key])
    sealed = old_cipher.encrypt(secret)
    rotated = rotating.rotate(sealed)
    assert secret not in sealed.ciphertext and (sealed.key_version, old_cipher.decrypt(sealed), rotating.decrypt(sealed), rotated.key_version, rotating.decrypt(rotated), new_only.decrypt(rotated)) == (
        old_cipher.current_version, secret, secret, rotating.current_version, secret, secret,
    )
    assert sealed.key_version != rotating.current_version != old_cipher.current_version
    for fn in (lambda: new_only.decrypt(sealed), lambda: old_cipher.rotate(Encrypted(ciphertext="not-a-valid-token", key_version=1)), lambda: FernetCipher([]), lambda: FernetCipher(["this-is-not-a-valid-fernet-key"])):
        with pytest.raises(LLMConfigError):
            fn()

    monkeypatch.setattr(settings, "llm_encryption_key_list", [], raising=False)
    with pytest.raises(LLMConfigError):
        build_cipher()
    monkeypatch.setattr(settings, "llm_encryption_key_list", [_key()], raising=False)
    cipher = build_cipher()
    assert cipher.decrypt(cipher.encrypt("x")) == "x"

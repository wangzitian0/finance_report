'AC-llm.1.2 EPIC-023'; from __future__ import annotations; import pytest; from cryptography.fernet import Fernet; from src.config import settings; from src.llm.base import FernetCipher, LLMConfigError, build_cipher; _key = lambda: Fernet.generate_key().decode('ascii')
def test_AC23_1_2_round_trips_a_provider_secret_without_storing_plaintext(): 'AC-llm.1.2'; cipher = FernetCipher([_key()]); secret = 'sk-super-secret-provider-key'; sealed = cipher.encrypt(secret); assert sealed.ciphertext != secret; assert secret not in sealed.ciphertext; assert sealed.key_version == cipher.current_version; assert cipher.decrypt(sealed) == secret
def test_AC23_1_3_rotation_is_single_pass_old_ciphertext_still_decrypts():
    'AC-llm.1.3'; old_key, new_key = (_key(), _key()); old_cipher = FernetCipher([old_key]); sealed = old_cipher.encrypt('provider-key'); assert sealed.key_version == old_cipher.current_version; rotating = FernetCipher([new_key, old_key]); assert rotating.current_version != old_cipher.current_version; assert rotating.decrypt(sealed) == 'provider-key'; assert sealed.key_version != rotating.current_version; rotated = rotating.rotate(sealed); assert rotated.key_version == rotating.current_version; assert rotating.decrypt(rotated) == 'provider-key'; new_only = FernetCipher([new_key]); assert new_only.current_version == rotating.current_version; assert new_only.decrypt(rotated) == 'provider-key'
    with pytest.raises(LLMConfigError): new_only.decrypt(sealed)
    'AC-llm.1.3'; 'AC-llm.1.3'; from src.llm.base import Encrypted; _m1_cipher = FernetCipher([_key()])
    with pytest.raises(LLMConfigError): _m1_cipher.rotate(Encrypted(ciphertext='not-a-valid-token', key_version=1))
    'AC-llm.1.4'; 'AC-llm.1.4'
    with pytest.raises(LLMConfigError): FernetCipher([])
    with pytest.raises(LLMConfigError): FernetCipher(['this-is-not-a-valid-fernet-key'])
def test_AC23_1_4_build_cipher_fails_closed_without_a_key(monkeypatch):
    'AC-llm.1.4'; monkeypatch.setattr(settings, 'llm_encryption_key_list', [], raising=False)
    with pytest.raises(LLMConfigError): build_cipher()
def test_AC23_1_4_build_cipher_uses_configured_keys(monkeypatch): 'AC-llm.1.4'; monkeypatch.setattr(settings, 'llm_encryption_key_list', [_key()], raising=False); cipher = build_cipher(); assert cipher.decrypt(cipher.encrypt('x')) == 'x'

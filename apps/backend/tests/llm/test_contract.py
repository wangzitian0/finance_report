'AC-llm.1.5 EPIC-023'; from __future__ import annotations; from collections.abc import AsyncIterator; from src.llm.base import ConfigSource, FernetCipher, LLMClient, Modality, ModelSpec, ProviderRef, Scene, SceneBinding, SecretCipher
class _FakeConfigSource:
    async def list_providers(self) -> list[ProviderRef]: return []
    async def get_provider(self, provider_id: str) -> ProviderRef | None: return None
    async def get_binding(self, scene: Scene) -> SceneBinding | None: return None
    async def is_configured(self) -> bool: return False
class _FakeClient:
    def stream(self, scene, messages, *, reasoning=None) -> AsyncIterator[str]: raise NotImplementedError
class _NotAConfigSource:
    async def list_providers(self) -> list[ProviderRef]: return []
def test_AC23_1_5_conforming_implementations_satisfy_the_protocols(): 'AC-llm.1.5'; assert isinstance(_FakeConfigSource(), ConfigSource); assert isinstance(_FakeClient(), LLMClient); 'AC-llm.1.5'; 'AC-llm.1.5'; from cryptography.fernet import Fernet; _m1_cipher = FernetCipher([Fernet.generate_key().decode('ascii')]); assert isinstance(_m1_cipher, SecretCipher); 'AC-llm.1.5'; 'AC-llm.1.5'; assert not isinstance(_NotAConfigSource(), ConfigSource); 'AC-llm.1.5'; 'AC-llm.1.5'; _m3_spec = ModelSpec(id='p/m', provider_id='p', modalities=frozenset({Modality.TEXT})); assert _m3_spec.accepts(Modality.TEXT); 'AC-llm.1.5'; 'AC-llm.1.5'; from src.llm.base import LLMBudgetExceeded, LLMConfigError, LLMError, ModelCatalogError; _m4_budget = LLMBudgetExceeded('over daily budget'); assert isinstance(_m4_budget, LLMError); assert _m4_budget.retryable is False; _m4_catalog = ModelCatalogError('catalogue unavailable', retryable=True); assert isinstance(_m4_catalog, LLMError); assert _m4_catalog.retryable is True; assert issubclass(LLMConfigError, LLMError)

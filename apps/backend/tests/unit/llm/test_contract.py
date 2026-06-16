"""The seam protocols are runtime-checkable and swappable (EPIC-023 AC23.1.5).

These tests pin the contract that lets EPIC A (litellm client) and EPIC B
(DB config) implement opposite sides independently: a conforming object must
satisfy ``isinstance`` against the protocol, and a non-conforming one must not.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from src.llm.common import (
    CatalogProvider,
    ChatResult,
    ConfigSource,
    CostMeter,
    FernetCipher,
    LLMClient,
    Message,
    Modality,
    ModelSpec,
    ProviderRef,
    ReasoningEffort,
    Scene,
    SceneBinding,
    SecretCipher,
    Usage,
)


class _FakeConfigSource:
    async def list_providers(self) -> list[ProviderRef]:
        return []

    async def get_provider(self, provider_id: str) -> ProviderRef | None:
        return None

    async def get_binding(self, scene: Scene) -> SceneBinding | None:
        return None

    async def is_configured(self) -> bool:
        return False


class _FakeClient:
    def stream(self, scene, messages, *, reasoning=None) -> AsyncIterator[str]:  # noqa: ANN001
        raise NotImplementedError

    def stream_json(self, scene, messages, *, reasoning=None) -> AsyncIterator[str]:  # noqa: ANN001
        raise NotImplementedError

    async def complete(
        self,
        scene: Scene,
        messages: Sequence[Message],
        *,
        reasoning: ReasoningEffort | None = None,
    ) -> ChatResult:
        return ChatResult(text="", model_id="x", usage=Usage())


class _FakeCatalog:
    async def list_models(self, *, provider_id=None, modality=None, free_only=False) -> list[ModelSpec]:  # noqa: ANN001
        return []


class _FakeCostMeter:
    async def check_budget(self) -> None:
        return None

    async def record(self, scene, model_id, usage, cost_usd) -> None:  # noqa: ANN001
        return None


class _NotAConfigSource:
    async def list_providers(self) -> list[ProviderRef]:
        return []

    # missing get_provider / get_binding / is_configured


def test_AC23_1_5_conforming_implementations_satisfy_the_protocols():
    """AC23.1.5: a conforming object passes isinstance for each seam protocol."""
    assert isinstance(_FakeConfigSource(), ConfigSource)
    assert isinstance(_FakeClient(), LLMClient)
    assert isinstance(_FakeCatalog(), CatalogProvider)
    assert isinstance(_FakeCostMeter(), CostMeter)


def test_AC23_1_5_fernet_cipher_is_a_secret_cipher():
    """AC23.1.5: the shipped FernetCipher satisfies the SecretCipher protocol."""
    from cryptography.fernet import Fernet

    cipher = FernetCipher([Fernet.generate_key().decode("ascii")])
    assert isinstance(cipher, SecretCipher)


def test_AC23_1_5_non_conforming_object_is_rejected():
    """AC23.1.5: a class missing protocol methods is not an instance — the contract bites."""
    assert not isinstance(_NotAConfigSource(), ConfigSource)


def test_AC23_1_5_modality_round_trips_via_model_spec():
    """AC23.1.5: ModelSpec uses the Modality enum the catalogue/binding share."""
    spec = ModelSpec(id="p/m", provider_id="p", modalities=frozenset({Modality.TEXT}))
    assert spec.accepts(Modality.TEXT)

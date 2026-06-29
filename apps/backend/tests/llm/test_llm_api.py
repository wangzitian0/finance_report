"""The ``/llm`` per-user config API + binding resolution (EPIC-023 AC23.4).

Exercises the runtime-config surface end to end through the authed client: the
first-run status flag, provider CRUD (with the API key encrypted at rest and never
returned), the model catalogue, and the scene→model bindings — plus the proof that
a user's binding drives model selection on the resolution path.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.identity import User
from src.llm.common import FernetCipher, Scene

pytestmark = pytest.mark.asyncio


@pytest.fixture
def cipher(monkeypatch) -> FernetCipher:
    """A configured cipher so POST /llm/providers can seal the key (default test
    env has no ``LLM_ENCRYPTION_KEYS``)."""
    instance = FernetCipher([Fernet.generate_key().decode("ascii")])
    monkeypatch.setattr("src.routers.llm.build_cipher", lambda: instance)
    return instance


async def _create_provider(client: AsyncClient, **overrides) -> dict:
    body = {
        "label": "my-zai",
        "protocol": "openai-compatible",
        "api_key": "sk-secret-123",
        "api_base": "https://api.z.ai",
        **overrides,
    }
    resp = await client.post("/llm/providers", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_AC23_4_1_config_status_flips_when_user_configures(client: AsyncClient, cipher) -> None:
    """AC23.4.1: status is False with no config, True once the user adds a provider."""
    before = await client.get("/llm/config/status")
    assert before.status_code == 200
    assert before.json() == {"configured": False}

    await _create_provider(client)

    after = await client.get("/llm/config/status")
    assert after.json() == {"configured": True}


async def test_AC23_4_2_provider_create_encrypts_and_never_returns_key(
    client: AsyncClient, db: AsyncSession, cipher
) -> None:
    """AC23.4.2: POST encrypts the key at rest; neither the response nor the row holds plaintext."""
    created = await _create_provider(client)
    assert "api_key" not in created
    assert created["has_api_key"] is True
    assert created["label"] == "my-zai"

    from sqlalchemy import select

    from src.models.llm_config import LlmProvider

    row = (await db.execute(select(LlmProvider).where(LlmProvider.id == created["id"]))).scalar_one()
    assert "sk-secret-123" not in row.api_key_ciphertext
    # The ciphertext still round-trips back to the original secret.
    from src.llm.common import Encrypted

    assert (
        cipher.decrypt(Encrypted(ciphertext=row.api_key_ciphertext, key_version=row.api_key_version)) == "sk-secret-123"
    )


async def test_AC23_4_2_provider_create_fails_closed_without_encryption_keys(client: AsyncClient) -> None:
    """AC23.4.2: with no ``LLM_ENCRYPTION_KEYS`` configured, POST fails closed (no plaintext stored)."""
    resp = await client.post(
        "/llm/providers",
        json={"label": "x", "protocol": "openai-compatible", "api_key": "sk-x"},
    )
    assert resp.status_code == 503


async def test_AC23_4_2_provider_list_and_delete(client: AsyncClient, cipher) -> None:
    """AC23.4.2: providers are listed for the user and deletable."""
    created = await _create_provider(client)
    listed = await client.get("/llm/providers")
    assert listed.status_code == 200
    ids = [p["id"] for p in listed.json()["providers"]]
    assert created["id"] in ids
    assert all("api_key" not in p for p in listed.json()["providers"])

    deleted = await client.delete(f"/llm/providers/{created['id']}")
    assert deleted.status_code == 200
    assert deleted.json() == {"id": created["id"], "deleted": True}
    after = await client.get("/llm/providers")
    assert created["id"] not in [p["id"] for p in after.json()["providers"]]


async def test_AC23_4_2_provider_rejects_non_http_api_base(client: AsyncClient, cipher) -> None:
    """AC23.4.2: a non-http(s) ``api_base`` is rejected at the schema boundary (422)."""
    resp = await client.post(
        "/llm/providers",
        json={"label": "x", "protocol": "openai-compatible", "api_key": "sk-x", "api_base": "not-a-url"},
    )
    assert resp.status_code == 422


async def test_AC23_4_2_provider_blank_api_base_persists_as_null(client: AsyncClient, db: AsyncSession, cipher) -> None:
    """AC23.4.2: a blank ``api_base`` normalises to NULL rather than an empty string."""
    created = await _create_provider(client, api_base="   ")
    assert created["api_base"] is None


async def test_AC23_4_2_delete_non_uuid_is_not_found(client: AsyncClient) -> None:
    """AC23.4.2: a non-UUID provider id deletes as 404, not a 500 from the UUID cast."""
    resp = await client.delete("/llm/providers/not-a-uuid")
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "api_base",
    [
        "http://localhost:8080",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.5",
        "https://vault.internal",
        # trailing-dot FQDNs resolve to the same host and must not bypass the guard
        "http://localhost.",
        "https://vault.internal.",
        "https://metadata.google.internal./computeMetadata/v1/",
        # legacy integer/hex/octal/short IPv4 encodings libc/curl accept
        "http://2130706433/",
        "http://0x7f000001/",
        "http://0177.0.0.1/",
        "http://127.1/",
        "http://0/",
    ],
)
async def test_AC23_4_9_provider_rejects_ssrf_api_base(client: AsyncClient, cipher, api_base: str) -> None:
    """AC23.4.9: api_base pointing at loopback/private/link-local/metadata/.internal is rejected (422)."""
    resp = await client.post(
        "/llm/providers",
        json={"label": "x", "protocol": "openai-compatible", "api_key": "sk-x", "api_base": api_base},
    )
    assert resp.status_code == 422


async def test_AC23_4_10_provider_count_capped(client: AsyncClient, cipher, monkeypatch) -> None:
    """AC23.4.10: creating providers beyond the per-user cap returns 409."""
    monkeypatch.setattr("src.routers.llm.MAX_PROVIDERS_PER_USER", 2)
    await _create_provider(client, label="p1")
    await _create_provider(client, label="p2")
    resp = await client.post(
        "/llm/providers",
        json={"label": "p3", "protocol": "openai-compatible", "api_key": "sk-x"},
    )
    assert resp.status_code == 409


async def test_AC23_4_3_catalog_lists_models_with_filters(client: AsyncClient) -> None:
    """AC23.4.3: the catalogue lists configured models and honours modality/free filters."""
    resp = await client.get("/llm/catalog")
    assert resp.status_code == 200
    models = resp.json()["models"]
    assert models, "expected at least the env-configured models"
    assert {"id", "provider_id", "modalities", "is_free", "supports_reasoning"} <= set(models[0])

    image = await client.get("/llm/catalog", params={"modality": "image"})
    assert image.status_code == 200
    assert all("image" in m["modalities"] for m in image.json()["models"])

    free = await client.get("/llm/catalog", params={"free_only": True})
    assert free.status_code == 200
    assert all(m["is_free"] for m in free.json()["models"])


async def test_AC23_4_4_scenes_round_trip(client: AsyncClient, cipher) -> None:
    """AC23.4.4: PUT /llm/scenes persists per-scene bindings and GET returns them."""
    provider = await _create_provider(client)
    payload = {
        "bindings": [
            {
                "scene": "advisor.chat",
                "provider_id": provider["id"],
                "model": "glm-4.6",
                "reasoning": "medium",
                "prefer_free": False,
                "fallback_model_ids": ["glm-4.6v"],
                "max_tokens": 2048,
            }
        ]
    }
    put = await client.put("/llm/scenes", json=payload)
    assert put.status_code == 200, put.text
    binding = put.json()["bindings"][0]
    assert binding["scene"] == "advisor.chat"
    assert binding["model"] == "glm-4.6"
    assert binding["reasoning"] == "medium"
    assert binding["fallback_model_ids"] == ["glm-4.6v"]

    got = await client.get("/llm/scenes")
    assert got.json()["bindings"][0]["model"] == "glm-4.6"


async def test_AC23_4_4_scenes_rejects_foreign_provider(client: AsyncClient, cipher) -> None:
    """AC23.4.4: a binding referencing a provider the user does not own is rejected."""
    from uuid import uuid4

    resp = await client.put(
        "/llm/scenes",
        json={"bindings": [{"scene": "advisor.chat", "provider_id": str(uuid4()), "model": "glm-4.6"}]},
    )
    assert resp.status_code == 400


async def test_AC23_4_5_user_binding_drives_resolution(
    client: AsyncClient, db: AsyncSession, test_user: User, cipher
) -> None:
    """AC23.4.5: the user's binding selects the scene's model on the resolution path."""
    provider = await _create_provider(client)
    await client.put(
        "/llm/scenes",
        json={"bindings": [{"scene": "advisor.chat", "provider_id": provider["id"], "model": "glm-4.6"}]},
    )

    from src.llm.factory import get_config_source

    binding = await get_config_source(test_user.id).get_binding(Scene.ADVISOR_CHAT)
    assert binding is not None
    # Qualified by the provider id so the client resolves the exact provider.
    assert binding.model_id == f"{provider['id']}/glm-4.6"


async def test_AC23_4_6_legacy_ai_models_endpoint_removed(client: AsyncClient) -> None:
    """AC23.4.6: the legacy ``GET /ai/models`` catalogue is retired in favour of /llm/catalog."""
    resp = await client.get("/ai/models")
    assert resp.status_code == 404

from __future__ import annotations

from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.identity import User
from src.llm import LlmProvider
from src.llm.base import Encrypted, FernetCipher, ProtocolFamily, Scene
from src.llm.extension.env_config import EnvConfigSource
from src.llm.extension.factory import get_config_source
from src.llm.orm.config import LlmSceneBinding

pytestmark = pytest.mark.asyncio


@pytest.fixture
def cipher(monkeypatch) -> FernetCipher:
    instance = FernetCipher([Fernet.generate_key().decode("ascii")])
    monkeypatch.setattr("src.routers.llm.build_cipher", lambda: instance)
    return instance


async def _create_provider(client: AsyncClient, **overrides) -> dict:
    body = {"label": "my-zai", "protocol": "openai-compatible", "api_key": "sk-secret-123", "api_base": "https://api.z.ai", **overrides}
    resp = await client.post("/llm/providers", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_AC23_4_1_and_2_provider_lifecycle_encryption_and_cap(
    client: AsyncClient, db: AsyncSession, cipher, monkeypatch
) -> None:
    assert (await client.get("/llm/config/status")).json() == {"configured": False}
    created = await _create_provider(client)
    assert "api_key" not in created and (created["has_api_key"], created["label"]) == (True, "my-zai")
    assert (await client.get("/llm/config/status")).json() == {"configured": True}

    row = (await db.execute(select(LlmProvider).where(LlmProvider.id == created["id"]))).scalar_one()
    assert "sk-secret-123" not in row.api_key_ciphertext
    assert cipher.decrypt(Encrypted(ciphertext=row.api_key_ciphertext, key_version=row.api_key_version)) == "sk-secret-123"

    blank = await _create_provider(client, label="blank", api_base="   ")
    assert blank["api_base"] is None

    listed = (await client.get("/llm/providers")).json()["providers"]
    assert created["id"] in [p["id"] for p in listed] and all("api_key" not in p for p in listed)

    deleted = await client.delete(f"/llm/providers/{created['id']}")
    assert (deleted.status_code, deleted.json()) == (200, {"id": created["id"], "deleted": True})
    assert created["id"] not in [p["id"] for p in (await client.get("/llm/providers")).json()["providers"]]

    monkeypatch.setattr("src.routers.llm.MAX_PROVIDERS_PER_USER", 1)
    assert (await client.post("/llm/providers", json={"label": "p3", "protocol": "openai-compatible", "api_key": "sk-x"})).status_code == 409


@pytest.mark.parametrize(
    ("method", "path", "json_body", "use_cipher", "expected_status"),
    [
        ("post", "/llm/providers", {"label": "x", "protocol": "openai-compatible", "api_key": "sk-x"}, False, 503),
        ("delete", "/llm/providers/not-a-uuid", None, False, 404),
        ("post", "/llm/providers", {"label": "x", "protocol": "openai-compatible", "api_key": "sk-x", "api_base": "not-a-url"}, True, 422),
        ("get", "/ai/models", None, False, 404),
    ],
)
async def test_provider_and_legacy_error_statuses(
    client: AsyncClient, monkeypatch, method: str, path: str, json_body: dict | None, use_cipher: bool, expected_status: int
) -> None:
    if use_cipher:
        instance = FernetCipher([Fernet.generate_key().decode("ascii")])
        monkeypatch.setattr("src.routers.llm.build_cipher", lambda: instance)
    kwargs = {"json": json_body} if json_body is not None else {}
    assert (await getattr(client, method)(path, **kwargs)).status_code == expected_status


@pytest.mark.parametrize(
    "api_base",
    [
        "http://localhost:8080",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.5",
        "https://vault.internal",
        "http://localhost.",
        "https://vault.internal.",
        "https://metadata.google.internal./computeMetadata/v1/",
        "http://2130706433/",
        "http://0x7f000001/",
        "http://0177.0.0.1/",
        "http://127.1/",
        "http://0/",
    ],
)
async def test_AC23_4_9_provider_rejects_ssrf_api_base(client: AsyncClient, cipher, api_base: str) -> None:
    resp = await client.post("/llm/providers", json={"label": "x", "protocol": "openai-compatible", "api_key": "sk-x", "api_base": api_base})
    assert resp.status_code == 422


async def test_AC23_4_3_catalog_lists_models_with_filters(client: AsyncClient) -> None:
    models = (await client.get("/llm/catalog")).json()["models"]
    assert models and {"id", "provider_id", "modalities", "is_free", "supports_reasoning"} <= set(models[0])
    image = await client.get("/llm/catalog", params={"modality": "image"})
    free = await client.get("/llm/catalog", params={"free_only": True})
    assert all("image" in m["modalities"] for m in image.json()["models"])
    assert all(m["is_free"] for m in free.json()["models"])


async def test_AC23_4_scenes_round_trip_roles_and_defaults(client: AsyncClient, db: AsyncSession, test_user: User, cipher) -> None:
    provider = await _create_provider(client)
    put = await client.put("/llm/scenes", json={"bindings": [{"scene": "advisor.chat", "provider_id": provider["id"], "model": "glm-5.1", "reasoning": "medium", "max_tokens": 2048}]})
    binding = put.json()["bindings"][0]
    assert (put.status_code, binding["scene"], binding["model"], binding["reasoning"], binding["max_tokens"], "prefer_free" in binding, "fallback_model_ids" in binding) == (200, "advisor.chat", "glm-5.1", "medium", 2048, False, False)
    assert (await client.get("/llm/scenes")).json()["bindings"][0]["model"] == "glm-5.1"
    assert (await get_config_source(test_user.id).get_binding(Scene.ADVISOR_CHAT)).model_id == f"{provider['id']}/glm-5.1"
    assert (await client.put("/llm/scenes", json={"bindings": [{"scene": "advisor.chat", "provider_id": str(uuid4()), "model": "glm-5.1"}]})).status_code == 400

    put_role = await client.put("/llm/scenes", json={"bindings": [{"scene": "advisor.chat", "provider_id": provider["id"], "model": "large", "reasoning": "high"}, {"scene": "extraction.vision", "provider_id": provider["id"], "model": "multimodal", "reasoning": "low"}]})
    assert (put_role.status_code, (await get_config_source(test_user.id).get_binding(Scene.ADVISOR_CHAT)).model_id, (await get_config_source(test_user.id).get_binding(Scene.EXTRACTION_VISION)).model_id) == (
        200, f"{provider['id']}/{settings.large_model}", f"{provider['id']}/{settings.multimodal_model}",
    )
    assert (await client.put("/llm/scenes", json={"bindings": [{"scene": "advisor.chat", "provider_id": provider["id"], "model": "glm-4.6"}]})).status_code in (400, 422)
    assert (EnvConfigSource.is_retired_scene_model("   "), EnvConfigSource.resolve_scene_model(Scene.ADVISOR_CHAT, None), EnvConfigSource.resolve_scene_model(Scene.ADVISOR_CHAT, "glm-4.6"), EnvConfigSource.resolve_scene_model(Scene.EXTRACTION_VISION, "provider1/glm-4.6")) == (
        True, settings.large_model, settings.large_model, settings.multimodal_model,
    )

    sealed = cipher.encrypt("sk-deploy-default")
    default_provider = LlmProvider(user_id=None, label="default-zai", protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key_ciphertext=sealed.ciphertext, api_key_version=sealed.key_version)
    db.add(default_provider)
    await db.flush()
    db.add(LlmSceneBinding(user_id=None, scene=Scene.ADVISOR_CHAT, provider_id=default_provider.id, model="glm-5.1"))
    await db.commit()
    assert (await get_config_source(None).get_binding(Scene.ADVISOR_CHAT)).model_id == f"{default_provider.id}/{settings.large_model}"

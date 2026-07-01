"""App-config base-currency endpoint + effective-accessor tests (#1340, Phase D).

Covers EPIC-012 AC12.39: GET/update of the effective base currency, ISO 4217
validation (invalid -> 422), DB persistence, and the single effective accessor
returning the persisted value (else the env default).
"""

import pytest
from common.testing.ac_proof import ac_proof
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.money import Currency
from src.config import settings
from src.services.app_config import get_effective_base_currency

pytestmark = pytest.mark.asyncio


@ac_proof(proof_id="test_app_config_base_currency_default", ac_ids=["AC12.39.2"], ci_tier="pr_ci", issue="#1340")
async def test_AC12_39_2_effective_accessor_falls_back_to_env_default(db: AsyncSession) -> None:
    """AC12.39.2: with no persisted row the accessor returns settings.base_currency."""
    assert await get_effective_base_currency(db) == Currency(settings.base_currency).code


@ac_proof(proof_id="test_app_config_get_default", ac_ids=["AC12.39.1"], ci_tier="pr_ci", issue="#1340")
async def test_AC12_39_1_get_returns_env_default_when_unset(client: AsyncClient) -> None:
    """AC12.39.1: GET returns the env-default base currency when nothing is persisted."""
    response = await client.get("/app-config/base-currency")
    assert response.status_code == 200
    assert response.json() == {"base_currency": Currency(settings.base_currency).code}


@ac_proof(proof_id="test_app_config_persist_and_effective", ac_ids=["AC12.39.4"], ci_tier="pr_ci", issue="#1340")
async def test_AC12_39_4_update_persists_and_effective_accessor_returns_new_value(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """AC12.39.4: PUT persists the override and the effective accessor returns it."""
    target = "EUR" if Currency(settings.base_currency).code != "EUR" else "USD"

    response = await client.put("/app-config/base-currency", json={"base_currency": target.lower()})
    assert response.status_code == 200
    assert response.json() == {"base_currency": target}

    # The effective accessor (read on a fresh session) now returns the persisted value.
    assert await get_effective_base_currency(db) == target

    # And GET reflects it too.
    get_response = await client.get("/app-config/base-currency")
    assert get_response.json() == {"base_currency": target}


@ac_proof(proof_id="test_app_config_invalid_rejected", ac_ids=["AC12.39.1"], ci_tier="pr_ci", issue="#1340")
async def test_AC12_39_1_invalid_currency_returns_422_and_is_not_persisted(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """AC12.39.1: a non-ISO-4217 code is rejected with 422 and never persisted."""
    response = await client.put("/app-config/base-currency", json={"base_currency": "XYZ"})
    assert response.status_code == 422

    # Nothing was persisted: effective value stays the env default.
    assert await get_effective_base_currency(db) == Currency(settings.base_currency).code

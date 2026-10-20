"""App-config base-currency endpoint + effective-accessor tests (#1340, Phase D; #2539).

Covers AC-audit.39: GET/update of the caller's effective base currency, ISO 4217
validation (invalid -> 422), DB persistence, the accessor precedence (own value,
operator default, env default), and user scope of the update.
"""

from uuid import uuid4

import pytest
from common.testing.ac_proof import ac_proof
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.money import Currency
from src.config import settings
from src.config_app import get_effective_base_currency
from src.identity import User, create_access_token
from src.platform import BASE_CURRENCY_KEY, AppConfig

pytestmark = pytest.mark.asyncio


@ac_proof(proof_id="test_app_config_base_currency_default", ac_ids=["AC-audit.39.2"], ci_tier="pr_ci", issue="#1340")
async def test_AC12_39_2_effective_accessor_falls_back_to_env_default(db: AsyncSession, test_user: User) -> None:
    """AC-audit.39.2: the accessor returns the user's value, else the operator default, else the env default."""
    default = Currency(settings.base_currency).code
    operator_value = "EUR" if default != "EUR" else "USD"
    own_value = "JPY" if default != "JPY" else "GBP"
    assert await get_effective_base_currency(db, user_id=test_user.id) == default

    db.add(AppConfig(key=BASE_CURRENCY_KEY, value=operator_value))
    await db.commit()
    assert await get_effective_base_currency(db, user_id=test_user.id) == operator_value

    test_user.base_currency = own_value
    await db.commit()
    assert await get_effective_base_currency(db, user_id=test_user.id) == own_value


@ac_proof(proof_id="test_app_config_get_default", ac_ids=["AC-audit.39.1"], ci_tier="pr_ci", issue="#1340")
async def test_AC12_39_1_get_returns_env_default_when_unset(client: AsyncClient) -> None:
    """AC-audit.39.1: AC12.39.1: GET returns the env-default base currency when nothing is persisted."""
    response = await client.get("/app-config/base-currency")
    assert response.status_code == 200
    assert response.json() == {"base_currency": Currency(settings.base_currency).code}


@ac_proof(proof_id="test_app_config_persist_and_effective", ac_ids=["AC-audit.39.4"], ci_tier="pr_ci", issue="#1340")
async def test_AC12_39_4_update_persists_and_effective_accessor_returns_new_value(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC-audit.39.4: AC12.39.4: PUT persists the override and the effective accessor returns it."""
    target = "EUR" if Currency(settings.base_currency).code != "EUR" else "USD"

    response = await client.put("/app-config/base-currency", json={"base_currency": target.lower()})
    assert response.status_code == 200
    assert response.json() == {"base_currency": target}

    # The effective accessor (read on a fresh session) now returns the persisted value.
    assert await get_effective_base_currency(db, user_id=test_user.id) == target

    # And GET reflects it too.
    get_response = await client.get("/app-config/base-currency")
    assert get_response.json() == {"base_currency": target}


@ac_proof(proof_id="test_app_config_invalid_rejected", ac_ids=["AC-audit.39.5"], ci_tier="pr_ci", issue="#1340")
async def test_AC12_39_1_invalid_currency_returns_422_and_is_not_persisted(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC-audit.39.5: AC12.39.1: a non-ISO-4217 code is rejected with 422 and never persisted."""
    response = await client.put("/app-config/base-currency", json={"base_currency": "XYZ"})
    assert response.status_code == 422

    # Nothing was persisted: effective value stays the env default.
    assert await get_effective_base_currency(db, user_id=test_user.id) == Currency(settings.base_currency).code


@ac_proof(proof_id="test_app_config_put_is_user_scoped", ac_ids=["AC-audit.39.6"], ci_tier="pr_ci", issue="#2539")
async def test_AC_audit_39_6_put_changes_only_the_callers_base_currency(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """AC-audit.39.6: a PUT by one user does not change the base currency of another user (#2539)."""
    default = Currency(settings.base_currency).code
    target = "EUR" if default != "EUR" else "USD"
    other = User(id=uuid4(), email=f"other-{uuid4()}@example.com", hashed_password="hashed")
    db.add(other)
    await db.commit()
    other_headers = {"Authorization": f"Bearer {create_access_token(data={'sub': str(other.id)})}"}

    response = await client.put("/app-config/base-currency", json={"base_currency": target})
    assert response.status_code == 200, response.text

    assert (await client.get("/app-config/base-currency")).json() == {"base_currency": target}
    other_response = await client.get("/app-config/base-currency", headers=other_headers)
    assert other_response.json() == {"base_currency": default}
    operator_row = await db.scalar(select(AppConfig).where(AppConfig.key == BASE_CURRENCY_KEY))
    assert operator_row is None

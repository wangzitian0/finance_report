import ast
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.audit import JournalEntrySourceType
from src.audit.money import Currency
from src.config import settings
from src.config_app import get_effective_base_currency
from src.identity import User, create_access_token
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    calculate_unrealized_fx_gains,
)
from src.platform import BASE_CURRENCY_KEY, AppConfig
from src.pricing import FxRate
from src.reporting import generate_balance_sheet, generate_income_statement

pytestmark = pytest.mark.asyncio


async def test_AC12_39_2_effective_accessor_falls_back_to_env_default(db: AsyncSession, test_user: User) -> None:
    import src.config_app as config_app

    assert not hasattr(config_app, "_user_base_currency_cache")
    assert not hasattr(config_app, "_operator_base_currency_cache")
    default = Currency(settings.base_currency).code
    operator_value = "EUR" if default != "EUR" else "USD"
    own_value = "JPY" if default != "JPY" else "GBP"
    assert await get_effective_base_currency(db, user_id=test_user.id) == default
    db.add(AppConfig(key=BASE_CURRENCY_KEY, value=f" {operator_value.lower()} "))
    await db.commit()
    assert await config_app.get_operator_base_currency(db) == operator_value
    assert await get_effective_base_currency(db, user_id=test_user.id) == operator_value
    test_user.base_currency = own_value
    await db.commit()
    assert await get_effective_base_currency(db, user_id=test_user.id) == own_value
    with pytest.raises(TypeError):
        await get_effective_base_currency(db)  # type: ignore[call-arg]


async def test_AC12_39_1_get_returns_env_default_when_unset(client: AsyncClient) -> None:
    response = await client.get("/users/me/settings/base-currency")
    assert response.status_code == 200
    assert response.json() == {"base_currency": Currency(settings.base_currency).code}


async def test_AC12_39_4_update_persists_and_effective_accessor_returns_new_value(
    client: AsyncClient, db: AsyncSession, test_user: User
) -> None:
    target = "EUR" if Currency(settings.base_currency).code != "EUR" else "USD"
    response = await client.put("/users/me/settings/base-currency", json={"base_currency": target.lower()})
    assert response.status_code == 200
    assert response.json() == {"base_currency": target}
    assert await get_effective_base_currency(db, user_id=test_user.id) == target
    get_response = await client.get("/users/me/settings/base-currency")
    assert get_response.json() == {"base_currency": target}


async def test_AC12_39_1_invalid_currency_returns_422_and_is_not_persisted(
    client: AsyncClient, db: AsyncSession, test_user: User
) -> None:
    response = await client.put("/users/me/settings/base-currency", json={"base_currency": "XYZ"})
    assert response.status_code == 422
    assert await get_effective_base_currency(db, user_id=test_user.id) == Currency(settings.base_currency).code


async def test_AC_audit_39_6_put_changes_only_the_callers_base_currency(client: AsyncClient, db: AsyncSession) -> None:
    default = Currency(settings.base_currency).code
    target = "EUR" if default != "EUR" else "USD"
    other = User(id=uuid4(), email=f"other-{uuid4()}@example.com", hashed_password="hashed")
    db.add(other)
    await db.commit()
    other_headers = {"Authorization": f"Bearer {create_access_token(data={'sub': str(other.id)})}"}
    response = await client.put("/users/me/settings/base-currency", json={"base_currency": target})
    assert response.status_code == 200, response.text
    assert (await client.get("/users/me/settings/base-currency")).json() == {"base_currency": target}
    other_response = await client.get("/users/me/settings/base-currency", headers=other_headers)
    assert other_response.json() == {"base_currency": default}
    operator_row = await db.scalar(select(AppConfig).where(AppConfig.key == BASE_CURRENCY_KEY))
    assert operator_row is None


async def test_AC_audit_39_7_only_boundary_modules_read_settings_base_currency() -> None:
    backend_root = Path(__file__).resolve().parents[2]
    src_root = backend_root / "src"
    allowed = {"src/config_app.py", "src/ledger/orm/journal.py", "src/ledger/extension/repository.py"}
    violators: set[str] = set()
    for path in sorted(src_root.rglob("*.py")):
        rel = path.relative_to(backend_root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute) or node.attr != "base_currency":
                continue
            owner = node.value
            (violators.add(rel) if rel not in allowed else None) if isinstance(
                owner, ast.Name
            ) and owner.id == "settings" else (violators.add(rel) if rel not in allowed else None) if isinstance(
                owner, ast.Attribute
            ) and owner.attr == "settings" else None
    assert violators == set(), f"Unexpected settings.base_currency readers: {sorted(violators)}"


async def test_AC_audit_39_8_usd_user_reports_and_revaluation_use_user_effective_base_currency(
    client: AsyncClient, db: AsyncSession, test_user: User
) -> None:
    assert Currency(settings.base_currency).code == "SGD"
    test_user.base_currency = "USD"
    await db.flush()
    entry_day = date(2025, 3, 10)
    report_day = date(2025, 3, 20)
    db.add_all(
        [
            FxRate(
                base_currency="EUR", quote_currency="USD", rate=Decimal("1.100000"), rate_date=entry_day, source="ECB"
            ),
            FxRate(
                base_currency="EUR", quote_currency="USD", rate=Decimal("1.200000"), rate_date=report_day, source="ECB"
            ),
        ]
    )
    usd_cash = Account(user_id=test_user.id, name="USD Checking", type=AccountType.ASSET, currency="USD")
    eur_cash = Account(user_id=test_user.id, name="EUR Vault", type=AccountType.ASSET, currency="EUR")
    usd_income = Account(user_id=test_user.id, name="USD Consulting", type=AccountType.INCOME, currency="USD")
    db.add_all([usd_cash, eur_cash, usd_income])
    await db.flush()
    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=entry_day,
        memo="USD and EUR consulting receipt",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
        base_currency="USD",
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=usd_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("200.00"),
                currency="USD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=eur_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="EUR",
                fx_rate=Decimal("1.100000"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=usd_income.id,
                direction=Direction.CREDIT,
                amount=Decimal("310.00"),
                currency="USD",
            ),
        ]
    )
    await db.commit()
    with pytest.raises(ValueError, match="base_currency is required"):
        await calculate_unrealized_fx_gains(db, test_user.id, report_day)
    with pytest.raises(ValueError, match="base_currency is required"):
        await generate_balance_sheet(db, test_user.id, as_of_date=report_day)
    with pytest.raises(ValueError, match="base_currency is required"):
        await generate_income_statement(db, test_user.id, start_date=date(2025, 3, 1), end_date=report_day)
    resolved_base = await get_effective_base_currency(db, user_id=test_user.id)
    assert resolved_base == "USD"
    reval = await calculate_unrealized_fx_gains(db, test_user.id, report_day, base_currency=resolved_base)
    assert reval.base_currency == "USD"
    assert len(reval.accounts_revalued) == 1
    assert reval.accounts_revalued[0].account_currency == "EUR"
    assert reval.total_unrealized_gain_loss == Decimal("10.00")
    bs_resp = await client.get(f"/reports/balance-sheet?as_of_date={report_day.isoformat()}")
    assert bs_resp.status_code == 200, bs_resp.text
    bs = bs_resp.json()
    assert bs["currency"] == "USD"
    assert Decimal(str(bs["total_assets"])) == Decimal("320.00")
    assert Decimal(str(bs["unrealized_fx_gain_loss"])) == Decimal("10.00")
    assert bs["is_balanced"] is True
    inc_resp = await client.get(f"/reports/income-statement?start_date=2025-03-01&end_date={report_day.isoformat()}")
    assert inc_resp.status_code == 200, inc_resp.text
    inc = inc_resp.json()
    assert inc["currency"] == "USD"
    assert Decimal(str(inc["total_income"])) == Decimal("310.00")
    inc_domain = await generate_income_statement(
        db,
        test_user.id,
        start_date=date(2025, 3, 1),
        end_date=report_day,
        currency=resolved_base,
        base_currency=resolved_base,
    )
    assert inc_domain["unrealized_fx_gain_loss"] == Decimal("10.00")

"""API response conformance vectors — builder + regen CLI (issue #1827).

Extends the #1167 cross-language conformance-vector pattern
(``common/audit/*/conformance/vectors.json``) from value semantics to API
response payloads: the backend OWNS a committed, sanitized wire-format vector
per endpoint, and the frontend test suite loads the SAME file verbatim as its
mock data (``apps/frontend/src/__tests__/fixtures/apiVectors.ts``). A backend
change to a served field's name/type/shape either reds the backend drift test
(``apps/backend/tests/schemas/test_api_response_vectors.py``) when vectors were
not regenerated, or reds the frontend tests consuming the regenerated vectors
— so contract drift can no longer ship green (G-contract-reddens).

Every value below is a sanitized placeholder (fixed UUIDs, "Vector *" names,
round amounts). NEVER copy real financial data into these builders.

Regenerate after an intentional serializer change::

    apps/backend/.venv/bin/python tools/api_response_vectors.py

then commit the rewritten ``common/<pkg>/conformance/vectors.json`` files
together with the serializer change (the FE tests tell you what the change
breaks on the consumer side).
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT_DIR / "apps" / "backend"
# Wrapper contract (AC8.13.56): repo root stays at sys.path[0] when a tools/
# script runs directly; the backend package root rides behind it.
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(1, str(BACKEND_ROOT))

from src.ledger import AccountType  # noqa: E402
from src.schemas.account import AccountListResponse, AccountResponse  # noqa: E402
from src.schemas.extraction import (  # noqa: E402
    AtomicTransactionResponse,
    BankStatementResponse,
    BankStatementStatusEnum,
)
from src.schemas.reporting import BalanceSheetResponse, ReportLine  # noqa: E402

# Fixed deterministic identifiers — placeholder UUIDs, never real ids.
_USER_ID = UUID("00000000-0000-4000-8000-00000000000a")
_TS_CREATED = datetime(2026, 1, 15, 8, 30, 0, tzinfo=timezone.utc)
_TS_UPDATED = datetime(2026, 1, 31, 9, 0, 0, tzinfo=timezone.utc)


def _wire(model: Any) -> dict[str, Any]:
    """Serialize exactly as FastAPI's ``response_model`` does (JSON mode)."""
    return model.model_dump(mode="json")


def build_balance_sheet_vector() -> dict[str, Any]:
    """GET /api/reports/balance-sheet — ``BalanceSheetResponse`` wire shape."""
    response = BalanceSheetResponse(
        as_of_date=date(2026, 1, 31),
        currency="SGD",
        assets=[
            ReportLine(
                account_id=UUID("00000000-0000-4000-8000-000000000101"),
                name="Vector Bank Checking",
                type=AccountType.ASSET,
                parent_id=None,
                amount=Decimal("8100.25"),
                confidence_tier="HIGH",
                provenance="imported",
            ),
            ReportLine(
                account_id=UUID("00000000-0000-4000-8000-000000000102"),
                name="Vector Brokerage Cash",
                type=AccountType.ASSET,
                parent_id=None,
                amount=Decimal("1399.75"),
                confidence_tier=None,
                provenance="manual",
            ),
        ],
        liabilities=[
            ReportLine(
                account_id=UUID("00000000-0000-4000-8000-000000000201"),
                name="Vector Credit Card",
                type=AccountType.LIABILITY,
                parent_id=None,
                amount=Decimal("2500.00"),
                confidence_tier="MEDIUM",
                provenance="imported",
            ),
        ],
        equity=[
            ReportLine(
                account_id=UUID("00000000-0000-4000-8000-000000000301"),
                name="Vector Opening Balances",
                type=AccountType.EQUITY,
                parent_id=None,
                amount=Decimal("6000.00"),
                confidence_tier=None,
                provenance="derived",
            ),
        ],
        confidence_tier="MEDIUM",
        total_assets=Decimal("9500.00"),
        total_liabilities=Decimal("2500.00"),
        total_equity=Decimal("6000.00"),
        net_income=Decimal("1000.00"),
        unrealized_fx_gain_loss=Decimal("0.00"),
        net_worth_adjustment_gain_loss=Decimal("0.00"),
        # Real emission shape from src/reporting/extension/_core.py — the
        # pre-vector hand-mocks used from_currency/to_currency, which had
        # already drifted from the served base_currency/quote_currency keys.
        fx_warnings=[
            {
                "type": "missing_fx_rate_partial_skip",
                "base_currency": "USD",
                "quote_currency": "SGD",
                "rate_date": "2026-01-31",
            }
        ],
        portfolio_warnings=[],
        opening_balance_warnings=[],
        equation_delta=Decimal("0.00"),
        is_balanced=True,
    )
    return {
        "method": "GET",
        "fe_path": "/api/reports/balance-sheet",
        "response_model": "src.schemas.reporting.BalanceSheetResponse",
        "response": _wire(response),
    }


def build_accounts_list_vector() -> dict[str, Any]:
    """GET /api/accounts — ``ListResponse[AccountResponse]`` wire shape."""
    items = [
        AccountResponse(
            name="Vector Checking",
            code="CHK-001",
            type=AccountType.ASSET,
            currency="SGD",
            parent_id=None,
            description="Everyday checking account (vector fixture)",
            id=UUID("00000000-0000-4000-8000-000000000401"),
            user_id=_USER_ID,
            is_active=True,
            is_system=False,
            balance=Decimal("8100.25"),
            created_at=_TS_CREATED,
            updated_at=_TS_UPDATED,
        ),
        AccountResponse(
            name="Vector Credit Card",
            code=None,
            type=AccountType.LIABILITY,
            currency="SGD",
            parent_id=None,
            description=None,
            id=UUID("00000000-0000-4000-8000-000000000402"),
            user_id=_USER_ID,
            is_active=True,
            is_system=False,
            balance=Decimal("2500.00"),
            created_at=_TS_CREATED,
            updated_at=_TS_UPDATED,
        ),
        AccountResponse(
            name="Vector Opening Balance Equity",
            code="OBE",
            type=AccountType.EQUITY,
            currency="SGD",
            parent_id=None,
            description=None,
            id=UUID("00000000-0000-4000-8000-000000000403"),
            user_id=_USER_ID,
            is_active=True,
            is_system=True,
            balance=None,
            created_at=_TS_CREATED,
            updated_at=_TS_UPDATED,
        ),
    ]
    response = AccountListResponse(items=items, total=3)
    return {
        "method": "GET",
        "fe_path": "/api/accounts",
        "response_model": "src.schemas.account.AccountListResponse",
        "response": _wire(response),
    }


def build_statement_upload_accepted_vector() -> dict[str, Any]:
    """POST /api/statements/upload (202) — freshly accepted upload status."""
    response = BankStatementResponse(
        id=UUID("00000000-0000-4000-8000-000000000601"),
        user_id=_USER_ID,
        account_id=None,
        file_path="uploads/vector/vector-bank-2026-01.pdf",
        original_filename="vector-bank-2026-01.pdf",
        institution="Vector Bank",
        account_last4="1234",
        currency=None,
        period_start=None,
        period_end=None,
        opening_balance=None,
        closing_balance=None,
        status=BankStatementStatusEnum.PARSING,
        confidence_score=None,
        balance_validated=None,
        validation_error=None,
        created_at=_TS_CREATED,
        updated_at=_TS_CREATED,
        transactions=[],
    )
    return {
        "method": "POST",
        "fe_path": "/api/statements/upload",
        "response_model": "src.schemas.extraction.BankStatementResponse",
        "response": _wire(response),
    }


def build_statement_parsed_vector() -> dict[str, Any]:
    """GET /api/statements/{id} — the same envelope once parsing settled."""
    statement_id = UUID("00000000-0000-4000-8000-000000000602")
    response = BankStatementResponse(
        id=statement_id,
        user_id=_USER_ID,
        account_id=UUID("00000000-0000-4000-8000-000000000401"),
        file_path="uploads/vector/vector-bank-2026-01.pdf",
        original_filename="vector-bank-2026-01.pdf",
        institution="Vector Bank",
        account_last4="1234",
        currency="SGD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1150.50"),
        status=BankStatementStatusEnum.PARSED,
        confidence_score=92,
        balance_validated=True,
        validation_error=None,
        created_at=_TS_CREATED,
        updated_at=_TS_UPDATED,
        transactions=[
            AtomicTransactionResponse(
                id=UUID("00000000-0000-4000-8000-000000000621"),
                statement_id=statement_id,
                txn_date=date(2026, 1, 10),
                description="VECTOR PAYROLL",
                amount=Decimal("200.50"),
                direction="IN",
                reference=None,
                currency="SGD",
                created_at=_TS_CREATED,
                updated_at=_TS_CREATED,
            ),
            AtomicTransactionResponse(
                id=UUID("00000000-0000-4000-8000-000000000622"),
                statement_id=statement_id,
                txn_date=date(2026, 1, 20),
                description="VECTOR GROCERY",
                amount=Decimal("50.00"),
                direction="OUT",
                reference="REF-0001",
                currency="SGD",
                created_at=_TS_CREATED,
                updated_at=_TS_CREATED,
            ),
        ],
    )
    return {
        "method": "GET",
        "fe_path": "/api/statements/{id}",
        "response_model": "src.schemas.extraction.BankStatementResponse",
        "response": _wire(response),
    }


_COMMENT = (
    "Backend-owned API response conformance vectors (#1827, pattern from "
    "#1167). Regenerated ONLY by tools/api_response_vectors.py from fixed "
    "sanitized inputs; the backend drift test recomputes and compares, and "
    "the frontend fixture helper (apps/frontend/src/__tests__/fixtures/"
    "apiVectors.ts) loads this exact file as mock data. Hand-editing or "
    "committing real financial data here is forbidden."
)


def build_vector_files() -> dict[Path, dict[str, Any]]:
    """Map each committed vectors.json path to its full regenerated payload."""
    return {
        ROOT_DIR / "common" / "reporting" / "conformance" / "vectors.json": {
            "_comment": _COMMENT,
            "endpoints": {"balance_sheet": build_balance_sheet_vector()},
        },
        ROOT_DIR / "common" / "ledger" / "conformance" / "vectors.json": {
            "_comment": _COMMENT,
            "endpoints": {"accounts_list": build_accounts_list_vector()},
        },
        ROOT_DIR / "common" / "extraction" / "conformance" / "vectors.json": {
            "_comment": _COMMENT,
            "endpoints": {
                "statement_upload_accepted": build_statement_upload_accepted_vector(),
                "statement_parsed": build_statement_parsed_vector(),
            },
        },
    }


def main() -> int:
    for path, payload in build_vector_files().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations
import json
from pathlib import Path
from common.platform.api_response_vectors import ROOT_DIR, build_vector_files

_committed = lambda path: json.loads(path.read_text(encoding="utf-8"))
_vector_file = lambda pkg: ROOT_DIR / "common" / pkg / "conformance" / "vectors.json"


def _regenerated(pkg: str) -> dict:
    files = build_vector_files()
    return files[_vector_file(pkg)]


def test_AC_reporting_api_vectors_1_balance_sheet_matches_committed_vector():
    "AC-reporting.api-vectors.1"
    regenerated = _regenerated("reporting")
    committed = _committed(_vector_file("reporting"))
    assert regenerated == committed, (
        "GET /api/reports/balance-sheet wire shape drifted from the committed vector. If the serializer change is intentional, regenerate via `apps/backend/.venv/bin/python tools/api_response_vectors.py` and fix the failing frontend consumers of the new shape."
    )
    response = committed["endpoints"]["balance_sheet"]["response"]
    for field in ("total_assets", "total_liabilities", "total_equity", "equation_delta"):
        assert isinstance(response[field], str), f"{field} must serialize as a decimal string"


def test_AC_ledger_api_vectors_1_accounts_list_matches_committed_vector():
    "AC-ledger.api-vectors.1"
    regenerated = _regenerated("ledger")
    committed = _committed(_vector_file("ledger"))
    assert regenerated == committed, (
        "GET /api/accounts wire shape drifted from the committed vector. If intentional, regenerate via `apps/backend/.venv/bin/python tools/api_response_vectors.py` and fix the failing frontend consumers."
    )
    response = committed["endpoints"]["accounts_list"]["response"]
    assert response["total"] == len(response["items"])
    assert len(response["items"]) > 0, "accounts_list vector items must not be empty"
    assert any((item["balance"] is not None for item in response["items"])), "at least one account must have a balance"
    for item in response["items"]:
        if item["balance"] is not None:
            assert isinstance(item["balance"], str), "balance must serialize as a decimal string"


def test_AC_extraction_api_vectors_1_statement_upload_matches_committed_vector():
    "AC-extraction.api-vectors.1"
    regenerated = _regenerated("extraction")
    committed = _committed(_vector_file("extraction"))
    assert regenerated == committed, (
        "POST /api/statements / GET /api/statements/{id} wire shape drifted from the committed vector. If intentional, regenerate via `apps/backend/.venv/bin/python tools/api_response_vectors.py` and fix the failing frontend consumers."
    )
    parsed = committed["endpoints"]["statement_parsed"]["response"]
    from decimal import Decimal

    assert len(parsed["transactions"]) > 0, "statement_parsed vector transactions must not be empty"
    delta = sum(
        (Decimal(t["amount"]) if t["direction"] == "IN" else -Decimal(t["amount"]) for t in parsed["transactions"])
    )
    assert Decimal(parsed["opening_balance"]) + delta == Decimal(parsed["closing_balance"])
    assert parsed["balance_validated"] is True


def test_base_and_chat_response_schemas():
    from datetime import date, datetime
    from decimal import Decimal
    from uuid import uuid4
    import pytest
    from pydantic import ValidationError
    from src.schemas.base import BaseResponse, ListResponse
    from src.schemas.chat import (
        ChatHistoryResponse,
        ChatMessagePreview,
        ChatMessageResponse,
        ChatMessageRoleEnum,
        ChatRequest,
        ChatSessionResponse,
        ChatSessionStatusEnum,
        ChatSuggestionsResponse,
    )
    from src.schemas.pricing import ManualValuationSnapshotCreate

    assert BaseResponse.model_config.get("from_attributes") is True
    assert ListResponse[str](items=["a"], total=1).total == 1
    assert (
        ManualValuationSnapshotCreate(
            component_type="rsu", as_of_date=date(2025, 3, 31), value=Decimal("10.00"), currency="usd", source="RSU"
        ).currency
        == "USD"
    )
    with pytest.raises(ValidationError):
        ChatRequest(message="")
    now = datetime.now()
    msg = ChatMessageResponse(
        id=uuid4(), session_id=uuid4(), role=ChatMessageRoleEnum.USER, content="hi", created_at=now
    )
    session = ChatSessionResponse(
        id=uuid4(),
        title="S",
        status=ChatSessionStatusEnum.ACTIVE,
        created_at=now,
        updated_at=now,
        last_active_at=now,
        message_count=1,
        last_message=ChatMessagePreview(role=ChatMessageRoleEnum.USER, content="hi", created_at=now),
        messages=[msg],
    )
    assert len(ChatHistoryResponse(sessions=[session]).sessions) == 1
    assert ChatSuggestionsResponse(suggestions=["Balance?"]).suggestions == ["Balance?"]

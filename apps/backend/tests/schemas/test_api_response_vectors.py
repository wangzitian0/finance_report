from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from common.platform.api_response_vectors import ROOT_DIR, build_vector_files


@pytest.mark.parametrize("pkg", ["reporting", "ledger", "extraction"])
def test_api_response_matches_committed_vector(pkg: str):
    vector_file = ROOT_DIR / "common" / pkg / "conformance" / "vectors.json"
    committed = json.loads(vector_file.read_text(encoding="utf-8"))
    assert build_vector_files()[vector_file] == committed
    endpoints = committed["endpoints"]
    if pkg == "reporting":
        resp = endpoints["balance_sheet"]["response"]
        assert all(isinstance(resp[f], str) for f in ("total_assets", "total_liabilities", "total_equity", "equation_delta"))
    elif pkg == "ledger":
        resp = endpoints["accounts_list"]["response"]
        assert resp["total"] == len(resp["items"]) > 0 and any(i["balance"] is not None for i in resp["items"])
        assert all(isinstance(i["balance"], str) for i in resp["items"] if i["balance"] is not None)
    else:
        parsed = endpoints["statement_parsed"]["response"]
        delta = sum(Decimal(t["amount"]) if t["direction"] == "IN" else -Decimal(t["amount"]) for t in parsed["transactions"])
        assert len(parsed["transactions"]) > 0 and parsed["balance_validated"] is True
        assert Decimal(parsed["opening_balance"]) + delta == Decimal(parsed["closing_balance"])


def test_base_and_chat_response_schemas():
    from src.schemas.base import BaseResponse, ListResponse
    from src.schemas.chat import ChatHistoryResponse, ChatMessagePreview, ChatMessageResponse, ChatMessageRoleEnum, ChatRequest, ChatSessionResponse, ChatSessionStatusEnum, ChatSuggestionsResponse
    from src.schemas.pricing import ManualValuationSnapshotCreate

    assert BaseResponse.model_config.get("from_attributes") is True and ListResponse[str](items=["a"], total=1).total == 1
    assert ManualValuationSnapshotCreate(component_type="rsu", as_of_date=date(2025, 3, 31), value=Decimal("10.00"), currency="usd", source="RSU").currency == "USD"
    with pytest.raises(ValidationError):
        ChatRequest(message="")
    now = datetime.now()
    msg = ChatMessageResponse(id=uuid4(), session_id=uuid4(), role=ChatMessageRoleEnum.USER, content="hi", created_at=now)
    session = ChatSessionResponse(
        id=uuid4(), title="S", status=ChatSessionStatusEnum.ACTIVE, created_at=now, updated_at=now, last_active_at=now, message_count=1, last_message=ChatMessagePreview(role=ChatMessageRoleEnum.USER, content="hi", created_at=now), messages=[msg]
    )
    assert len(ChatHistoryResponse(sessions=[session]).sessions) == 1 and ChatSuggestionsResponse(suggestions=["Balance?"]).suggestions == ["Balance?"]

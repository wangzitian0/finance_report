'EPIC-023'; from __future__ import annotations; import json; from decimal import Decimal; from pathlib import Path; import pytest; from src.extraction import DocumentSource; from src.llm import accumulate_stream, stream_ai_json; _TEXT_MODEL = 'glm-5.2'; _TEXT_MAX_TOKENS = 512; _TEXT_PROMPT = 'Extract this bank statement as strict JSON only (no prose, no markdown fence) with keys opening_balance, closing_balance, transactions (a list of {date, description, amount}). Amounts are negative for debits, positive for credits.'; _TEXT_STATEMENT = 'Opening balance: 100.00\n2026-01-02  Coffee shop        -5.00\n2026-01-05  Salary credit      +50.00\n2026-01-09  Groceries          -15.00\nClosing balance: 130.00\n'; _TEXT_MESSAGES = [{'role': 'user', 'content': _TEXT_PROMPT + '\n\n' + _TEXT_STATEMENT}]; _TEXT_OPENING = Decimal('100.00'); _TEXT_CLOSING = Decimal('130.00'); _TEXT_TOLERANCE = Decimal('0.01'); _TEXT_TXN_COUNT = 3
def _loads_tolerant(content: str) -> dict:
    text = content.strip()
    if text.startswith('```'): text = text.split('\n', 1)[1] if '\n' in text else text; text = text.rsplit('```', 1)[0]
    return json.loads(text)
async def test_AC23_6_extraction_text_happy_path_via_replay() -> None: stream = stream_ai_json(messages=_TEXT_MESSAGES, model=_TEXT_MODEL, max_tokens=_TEXT_MAX_TOKENS, temperature=0.0, thinking={'type': 'disabled'}); content = await accumulate_stream(stream); data = _loads_tolerant(content); opening = Decimal(str(data['opening_balance'])); closing = Decimal(str(data['closing_balance'])); txns = data['transactions']; net = sum((Decimal(str(t['amount'])) for t in txns), Decimal('0')); assert abs(opening - _TEXT_OPENING) <= _TEXT_TOLERANCE; assert abs(closing - _TEXT_CLOSING) <= _TEXT_TOLERANCE; assert len(txns) == _TEXT_TXN_COUNT; assert abs(opening + net - closing) <= _TEXT_TOLERANCE; from src.extraction.base.validation import validate_balance; from src.extraction.extension.service import ExtractionService; _m1_service = ExtractionService(); _m1_service.api_key = _m1_service.api_key or 'replay'; _m1_result = await _m1_service.extract_financial_data(file_content=_VISION_PDF.read_bytes(), institution='ACME', file_type='pdf', filename='simple_statement.pdf'); assert len(_m1_result['transactions']) == 3; assert validate_balance(_m1_result)['balance_valid'] is True; _m2_stream = stream_ai_json(messages=_DUP_MESSAGES, model=_DUP_MODEL, max_tokens=_DUP_MAX_TOKENS, temperature=0.0, thinking={'type': 'disabled'}); _m2_content = await accumulate_stream(_m2_stream); _m2_data = _loads_tolerant(_m2_content); _m2_opening = Decimal(str(_m2_data['opening_balance'])); _m2_closing = Decimal(str(_m2_data['closing_balance'])); _m2_txns = _m2_data['transactions']; _m2_amounts = [Decimal(str(_m2_t['amount'])) for _m2_t in _m2_txns]; _m2_net = sum(_m2_amounts, Decimal('0')); assert len(_m2_txns) == 3; assert sum((1 for _m2_a in _m2_amounts if _m2_a == _DUP_DEPOSIT)) == 2; assert abs(_m2_opening - _DUP_OPENING) <= _TEXT_TOLERANCE; assert abs(_m2_closing - _DUP_CLOSING) <= _TEXT_TOLERANCE; assert abs(_m2_opening + _m2_net - _m2_closing) <= _TEXT_TOLERANCE
_VISION_PDF = Path(__file__).resolve().parents[1] / 'fixtures' / 'vision' / 'simple_statement.pdf'; _DUP_MODEL = 'glm-5.2'; _DUP_MAX_TOKENS = 512; _DUP_STATEMENT = 'Opening balance: 1000.00\n2026-02-01  Deposit ABC        +250.00\n2026-02-01  Deposit ABC        +250.00\n2026-02-03  Service fee         -10.00\nClosing balance: 1490.00\n'; _DUP_MESSAGES = [{'role': 'user', 'content': _TEXT_PROMPT + '\n\n' + _DUP_STATEMENT}]; _DUP_OPENING = Decimal('1000.00'); _DUP_CLOSING = Decimal('1490.00'); _DUP_DEPOSIT = Decimal('250.00'); _VISION_DIR = Path(__file__).resolve().parents[1] / 'fixtures' / 'vision'
def _stub_env_provider(monkeypatch: pytest.MonkeyPatch) -> None: from src.config import settings; monkeypatch.setattr(settings, 'ai_api_key', 'sk-test-replay-dummy', raising=False); monkeypatch.setattr(settings, 'ai_provider', 'openai-compatible-test', raising=False)
async def test_AC_llm_14_1_missing_period_remains_review_only_via_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-llm.14.1: A payload without a statement period stays review-only.

    A unit stub, not a replay: a model that reads a document infers the month from its row dates, so a real
    recording cannot hold a missing period. The payload is the one a model returns when it keeps the period null.
    """
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from src.extraction.extension.service import ExtractionService

    payload = {
        "institution": "ACME",
        "account_last4": "5678",
        "currency": "SGD",
        "period_start": None,
        "period_end": None,
        "opening_balance": "1000.00",
        "closing_balance": "1720.00",
        "transactions": [
            {"date": "2026-03-02", "description": "Salary credit", "amount": "2000.00", "direction": "IN"},
            {"date": "2026-03-05", "description": "Rent payment", "amount": "1200.00", "direction": "OUT"},
            {"date": "2026-03-20", "description": "Groceries", "amount": "80.00", "direction": "OUT"},
        ],
    }
    service = ExtractionService()
    monkeypatch.setattr(service, "extract_financial_data", AsyncMock(return_value=payload))
    source = DocumentSource.resolve(path=Path("statement.pdf"), content=b"stub")
    result = await service.parse_document(source, institution="ACME", user_id=uuid4(), file_type="pdf")
    assert result.balance_validated is True
    assert result.period_start is None
    assert result.period_end is None
    assert result.missing_required_facts == ("period",)
    assert result.review_reasons == ("Source is missing required facts: statement period",)
    assert len(result.transactions) == 3
async def test_AC_llm_14_2_no_recoverable_date_anywhere_rejects_cleanly_via_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    'AC-llm.14.2'; from uuid import uuid4; from src.extraction.extension.service import ExtractionError, ExtractionService; _stub_env_provider(monkeypatch); service = ExtractionService(); service.api_key = service.api_key or 'replay'; pdf = _VISION_DIR / 'unhappy_no_dates_at_all.pdf'
    with pytest.raises(ExtractionError, match='Transaction missing required fields: date or amount'): await service.parse_document(DocumentSource.resolve(path=pdf, content=pdf.read_bytes()), institution='ACME', user_id=uuid4(), file_type='pdf')
async def test_AC_llm_14_3_unreconciled_balance_quarantines_to_rejected_via_replay(db, test_user, monkeypatch: pytest.MonkeyPatch) -> None: 'AC-llm.14.3'; from sqlalchemy import select; from src.extraction import BankStatementStatus; from src.extraction.extension.service import ExtractionService; from src.extraction.orm.layer2 import AtomicTransaction; _stub_env_provider(monkeypatch); service = ExtractionService(); service.api_key = service.api_key or 'replay'; pdf = _VISION_DIR / 'unhappy_balance_unreconciled.pdf'; from tests.statement_ingestion import parse_and_load_statement_projection; result, summary, _transactions = await parse_and_load_statement_projection(service, db=db, source=DocumentSource.resolve(path=pdf, content=pdf.read_bytes()), institution='ACME', user_id=test_user.id, file_type='pdf'); assert summary.status == BankStatementStatus.REJECTED; assert result.balance_validated is False; persisted = await db.execute(select(AtomicTransaction).where(AtomicTransaction.user_id == test_user.id)); assert persisted.scalars().all() == []

from __future__ import annotations

import contextlib
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.config import Settings, settings
from src.extraction import DocumentSource
from src.extraction.base.decoding import JSON_MAX_TOKENS
from src.extraction.extension import service as extraction_mod
from src.extraction.extension.prompts.statement import get_parsing_prompt
from src.extraction.extension.service import ExtractionError, ExtractionService, _tolerant_parse_date
from tests._support.fake_llm import install_fake_model


def test_AC13_19_tolerant_dates_and_prompt():
    prompt = get_parsing_prompt("DBS")
    assert all(s in prompt for s in ("Normalize EVERY date to ISO YYYY-MM-DD", "never echo a non-ISO source format", "2025年01月15日 -> 2025-01-15"))
    assert all(_tolerant_parse_date(s) == date(2025, 1, 15) for s in ("2025-01-15", "2025/01/15", "2025.01.15", "2025年01月15日", "15/01/2025", "15 Jan 2025", "2025-01-15T00:00:00"))
    assert all(_tolerant_parse_date(bad) is None for bad in (None, "", "   ", "None", "null", "n/a", "-", "not-a-date"))


async def test_AC13_19_2_3_chinese_dates_and_quarantine():
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value={"period_start": "2025年01月01日", "period_end": "2025年01月31日", "currency": "CNY", "opening_balance": "100.00", "closing_balance": "150.00", "transactions": [{"date": "2025年01月15日", "amount": "50.00", "direction": "IN", "description": "工资"}]})
    result = await service.parse_document(DocumentSource.resolve(path=Path("zh.pdf"), content=b"content"), institution="CMB", user_id=uuid4())
    assert (result.period_start, result.period_end, len(result.transactions), result.transactions[0].transaction_date) == (date(2025, 1, 1), date(2025, 1, 31), 1, date(2025, 1, 15))

    service.extract_financial_data = AsyncMock(return_value={"period_start": "2025-01-01", "period_end": "2025-01-31", "currency": "SGD", "opening_balance": "100.00", "closing_balance": "150.00", "transactions": [{"date": "garbage-date", "amount": "10.00", "direction": "IN", "description": "Bad"}, {"date": "2025/01/20", "amount": "50.00", "direction": "IN", "description": "Good"}]})
    with pytest.raises(ExtractionError, match="Transaction date"):
        await service.parse_document(DocumentSource.resolve(path=Path("mixed.pdf"), content=b"content"), institution="DBS", user_id=uuid4())


async def test_seed_determinism_and_decode_parameters(monkeypatch):
    service = ExtractionService()
    sent = install_fake_model(monkeypatch, '{"ok": true}')
    with patch.object(service, "api_key", "test-key"), patch.object(settings, "ai_json_seed", 1234):
        res = await service._extract_json_with_model(messages=[{"role": "user", "content": "x"}], model="test-model")
    assert res == {"ok": True} and sent.decodings[0].seed == 1234

    with patch.object(service, "api_key", "test-key"):
        await service._extract_json_with_model(
            messages=[{"role": "user", "content": "x"}], model="test-model", seed_override=7
        )
    assert (sent.decodings[1].temperature, sent.decodings[1].seed, sent.extra_bodies[1]) == (
        0.0,
        7,
        {"do_sample": False, "max_tokens": JSON_MAX_TOKENS},
    )

    assert (Settings(AI_JSON_SEED="").ai_json_seed, Settings(AI_JSON_SEED="   ").ai_json_seed, Settings(AI_JSON_SEED="7").ai_json_seed) == (None, None, 7)
    monkeypatch.delenv("AI_JSON_SEED", raising=False)
    assert Settings(_env_file=None).ai_json_seed is None

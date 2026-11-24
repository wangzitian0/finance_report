from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests._support.fake_llm import install_fake_model
from src.config import Settings
from src.extraction.extension.service import ExtractionError, ExtractionService


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('```json\n{"institution": "DBS", "transactions": []}\n```', {"institution": "DBS", "transactions": []}),
        ('Here is the result:\n```\n{"a": 1, "nested": {"b": 2}}\n```\nDone.', {"a": 1, "nested": {"b": 2}}),
        ('```json {"institution": "DBS", "transactions": []}```', {"institution": "DBS", "transactions": []}),
        ('{"x": "y"}', {"x": "y"}),
        ('```json\n{"note": "balance {pending}", "ok": true}\n```', {"note": "balance {pending}", "ok": True}),
        ('{"path": "C:\\\\Users\\\\x", "quote": "she said \\"hi\\"", "ok": true}', {"path": "C:\\Users\\x", "quote": 'she said "hi"', "ok": True}),
        ('Here is the format I will use: {"institution": "Example", "transactions": []}\nNow the actual data:\n{"institution": "DBS", "opening_balance": "1000.00", "closing_balance": "1100.00", "transactions": [{"amount": "100.00", "direction": "IN"}]}', {"institution": "DBS", "opening_balance": "1000.00", "closing_balance": "1100.00", "transactions": [{"amount": "100.00", "direction": "IN"}]}),
        ('{"institution": "DBS", "transactions": []}\nnote: {oops', {"institution": "DBS", "transactions": []}),
        ('note: {oops\n{"institution": "DBS", "transactions": []}', {"institution": "DBS", "transactions": []}),
    ],
)
def test_repair_json_object_recovers_valid_objects(raw, expected):
    repaired = ExtractionService._repair_json_object(raw)
    assert repaired is not None and json.loads(repaired) == expected


@pytest.mark.parametrize("raw", ["totally not json", "", '{"a": 1, "b": 2', '{"note": "a } b"'])
def test_repair_json_object_returns_none_when_unrecoverable(raw):
    assert ExtractionService._repair_json_object(raw) is None


async def test_extraction_salvages_and_rejects_fenced_and_truncated_responses(monkeypatch):
    service = ExtractionService()
    install_fake_model(monkeypatch, '```json\n{"institution": "DBS", "transactions": []}\n```')
    with patch.object(service, "api_key", "test-key"):
        assert await service._extract_json_with_model(messages=[{"role": "user", "content": "x"}], model="test-model") == {"institution": "DBS", "transactions": []}

    truncated = '{"institution": "DBS POSB", "account_last4": "8123", "currency": "SGD", "opening_balance": "124781.91", "closing_balance": null, "transactions": [{"date": "2024-11-01", "description": "PayNow Transfer", "amount": "15.00", "direction": "OUT", "currency": "SGD", "balance_after": "124766.91"}, {"date": "2024-11-02", "description": "Truncated mid-row'
    assert Settings().ai_json_max_tokens == 32768 and ExtractionService._repair_json_object(truncated) is None
    for bad, match in [("not json at all", None), (truncated, "json_parse")]:
        install_fake_model(monkeypatch, bad)
        with patch.object(service, "api_key", "test-key"), pytest.raises(ExtractionError, match=match):
            await service._extract_json_with_model(messages=[{"role": "user", "content": "x"}], model="test-model")

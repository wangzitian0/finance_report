from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from src.audit import canonical_json_digest, text_digest


def test_AC_audit_44_1_canonical_json_digest_keeps_the_old_bytes() -> None:
    flat, text_input = (
        {"package": "pricing", "policy": "valuation-attestation", "producer_version": "1"},
        "reviewed-statement-envelope:CODE-ONLY:exact:v1",
    )
    non_json = {
        "id": UUID("12345678-1234-5678-1234-567812345678"),
        "date": date(2026, 10, 27),
        "dt": datetime(2026, 10, 27, 8, 30, tzinfo=UTC),
        "amount": Decimal("10.50"),
    }
    assert (
        canonical_json_digest(flat),
        canonical_json_digest({"producer_version": "1", "policy": "valuation-attestation", "package": "pricing"}),
        text_digest(json.dumps(flat, sort_keys=True, separators=(",", ":"))),
        text_digest(text_input),
        canonical_json_digest(text_input),
        canonical_json_digest(text_input) != text_digest(text_input),
        canonical_json_digest(non_json, default=str),
    ) == (
        "96b00c594009839c762e1049ea37ec68334441826c6e186ce1dca09b6c8fe83b",
        "96b00c594009839c762e1049ea37ec68334441826c6e186ce1dca09b6c8fe83b",
        "96b00c594009839c762e1049ea37ec68334441826c6e186ce1dca09b6c8fe83b",
        "7eada8b15748ac904728c7cf00f0f319063fd4b99c343264ea376b0f7e7af4a0",
        "9cb6e4c92aceede709df2115459de8fa41598190135f00436a221ca1d4a5dfd3",
        True,
        "9741c3952c78bcd5f60e20dde59dd5d5198bccc8afae3957514904d6bdf4a0ec",
    )
    assert canonical_json_digest(text_input) == text_digest(json.dumps(text_input)) and canonical_json_digest(
        non_json, default=str
    ) == canonical_json_digest({k: str(v) for k, v in non_json.items()})
    with pytest.raises(TypeError):
        canonical_json_digest(non_json)

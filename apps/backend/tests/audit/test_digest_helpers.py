"""AC-audit.44.1: canonical_json_digest and text_digest preserve exact SHA-256 bytes (#2768)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from src.audit import canonical_json_digest, text_digest

UUID1 = UUID("12345678-1234-5678-1234-567812345678")


def test_AC_audit_44_1_canonical_json_digest_keeps_the_old_bytes() -> None:
    """AC-audit.44.1: canonical_json_digest and text_digest preserve historical bytes and encoding rules."""
    flat = {
        "package": "pricing",
        "policy": "valuation-attestation",
        "producer_version": "1",
    }
    flat_reordered = {
        "producer_version": "1",
        "policy": "valuation-attestation",
        "package": "pricing",
    }
    expected_flat = "96b00c594009839c762e1049ea37ec68334441826c6e186ce1dca09b6c8fe83b"

    assert canonical_json_digest(flat) == expected_flat
    assert canonical_json_digest(flat_reordered) == expected_flat
    assert text_digest(json.dumps(flat, sort_keys=True, separators=(",", ":"))) == expected_flat

    text_input = "reviewed-statement-envelope:CODE-ONLY:exact:v1"
    assert text_digest(text_input) == "7eada8b15748ac904728c7cf00f0f319063fd4b99c343264ea376b0f7e7af4a0"
    assert canonical_json_digest(text_input) == "9cb6e4c92aceede709df2115459de8fa41598190135f00436a221ca1d4a5dfd3"
    assert canonical_json_digest(text_input) == text_digest(json.dumps(text_input))
    assert canonical_json_digest(text_input) != text_digest(text_input)

    non_json = {
        "id": UUID1,
        "date": date(2026, 10, 27),
        "dt": datetime(2026, 10, 27, 8, 30, tzinfo=UTC),
        "amount": Decimal("10.50"),
    }
    with pytest.raises(TypeError):
        canonical_json_digest(non_json)

    assert (
        canonical_json_digest(non_json, default=str)
        == "9741c3952c78bcd5f60e20dde59dd5d5198bccc8afae3957514904d6bdf4a0ec"
    )
    assert canonical_json_digest(non_json, default=str) == canonical_json_digest(
        {k: str(v) for k, v in non_json.items()}
    )

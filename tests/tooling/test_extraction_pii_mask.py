"""Tests for the extraction-output PII mask (EPIC-023 cassette corpus).

Committed cassette responses + ground truth are masked by this module so neither
identity meta nor counterparty names land in git, while flow values (date/amount/
direction/balance) stay intact for the graded-eval and balance-chain gates.
"""

from __future__ import annotations

from tools._lib.fixtures.extraction_pii_mask import (
    mask_description,
    mask_extraction,
    mask_response_text,
    source_ref,
)


def test_meta_identity_fields_are_starred() -> None:
    """Identity meta -> ``**``; institution/period/currency (not PII) are kept."""
    masked = mask_extraction(
        {
            "institution": "Progressive National Bank",
            "currency": "INR",
            "period_start": "2024-01-01",
            "account_last4": "6112",
            "account_holder": "John Tan",
            "address": "12 Main St",
        }
    )
    assert masked["institution"] == "Progressive National Bank"
    assert masked["currency"] == "INR"
    assert masked["period_start"] == "2024-01-01"
    assert masked["account_last4"] == "**"
    assert masked["account_holder"] == "**"
    assert masked["address"] == "**"


def test_description_is_unique_but_unrecoverable_pseudonym() -> None:
    """A description becomes a sha256-derived ``<2hex>`` + stars + ``<2hex>`` token,
    LENGTH-PRESERVING: distinguishable (equal→equal, distinct→distinct), not recoverable
    (no real characters leak), and the same length as the original."""
    import re

    pat = re.compile(r"[0-9a-f]{2}\*+[0-9a-f]{2}")
    src = "ACME TRADING PTE LTD"
    a = mask_description(src)
    assert pat.fullmatch(a)
    assert len(a) == len(src)  # length preserved
    assert "ACM" not in a and "LTD" not in a  # original chars do NOT leak
    # equal content (case-insensitive, same length) -> equal token; distinct -> distinct
    assert a == mask_description("acme trading pte ltd")  # same length, just case
    assert a != mask_description("CLOTHING INDUSTRIES LTD")


def test_description_mask_is_idempotent() -> None:
    once = mask_description("ACME TRADING PTE LTD")
    assert mask_description(once) == once  # re-masking a pseudonym is a no-op


def test_raw_text_and_reference_are_masked() -> None:
    """The biggest residual PII surface: the audit-trail `raw_text` (whole original
    line — counterparty names, branch/reference numbers) and `reference` must be masked,
    not just `description`."""
    masked = mask_extraction(
        {
            "transactions": [
                {
                    "description": "By CITI BANK",
                    "amount": "165870.21",
                    "reference": "210968206613",
                    "cheque_no": "712481",
                    "branch_code": "3421",
                    "raw_text": "01-01-2024 By CITI BANK N.A., PHARMACY PRODUCTS LTD Rs. 165,870.21",
                }
            ]
        }
    )
    txn = masked["transactions"][0]
    assert txn["raw_text"] == "**"
    assert txn["reference"] == "**"
    assert txn["cheque_no"] == "**"
    assert txn["branch_code"] == "**"
    assert txn["amount"] == "165870.21"  # flow value kept
    assert "CITI BANK" not in str(
        txn
    )  # no counterparty name survives anywhere in the row


def test_real_name_description_is_pseudonymised_not_leaked() -> None:
    """A real counterparty name in a description leaves no recoverable trace: the token
    is hex+stars+hex (length-preserved), and meta/flow/symbol are handled as expected."""
    masked = mask_extraction(
        {
            "institution": "DBS Bank",
            "transactions": [
                {
                    "description": "FROM: JOHN DOE PAYNOW",
                    "amount": "190.00",
                    "direction": "IN",
                    "balance_after": "42869.09",
                }
            ],
            "positions": [
                {"symbol": "AAPL", "quantity": "10", "market_value": "1900.25"}
            ],
        }
    )
    txn = masked["transactions"][0]
    assert "JOHN" not in str(masked) and "DOE" not in str(
        masked
    )  # no real name survives
    assert len(txn["description"]) == len("FROM: JOHN DOE PAYNOW")  # length preserved
    assert txn["amount"] == "190.00" and txn["balance_after"] == "42869.09"  # flow kept
    assert masked["positions"][0]["symbol"] == "AAPL"  # public symbol kept
    assert masked["institution"] == "DBS Bank"  # institution name not PII


def test_flow_values_are_kept() -> None:
    """date / amount / direction / balance carry no identity PII and are preserved."""
    masked = mask_extraction(
        {
            "transactions": [
                {
                    "date": "2024-01-01",
                    "description": "ACME PTE LTD",
                    "amount": "10.00",
                    "direction": "OUT",
                    "balance_after": "90.00",
                }
            ]
        }
    )
    txn = masked["transactions"][0]
    assert txn["date"] == "2024-01-01"
    assert txn["amount"] == "10.00"
    assert txn["direction"] == "OUT"
    assert txn["balance_after"] == "90.00"
    assert txn["description"] != "ACME PTE LTD" and len(txn["description"]) == len(
        "ACME PTE LTD"
    )  # pseudonymised, length kept


def test_mask_response_text_handles_fenced_json() -> None:
    out = mask_response_text(
        '```json\n{"account_holder": "Jane Doe", "transactions": []}\n```'
    )
    assert "Jane Doe" not in out
    assert "**" in out
    # non-JSON passes through unchanged
    assert mask_response_text("not json") == "not json"


def test_source_ref_url_vs_hash() -> None:
    assert source_ref(hf_url="https://hf/x.pdf") == {
        "origin": "huggingface",
        "url": "https://hf/x.pdf",
    }
    ref = source_ref(file_bytes=b"abc")
    assert ref["origin"] == "local" and len(ref["sha256"]) == 64

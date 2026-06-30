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


def test_description_keeps_first3_star_last3() -> None:
    assert mask_description("ACME TRADING PTE LTD") == "ACM***LTD"
    assert mask_description("NEFT Cr-...CLOTHING INDUSTRIES LTD--") == "NEF***D--"
    assert mask_description("short") == "*****"  # <= 6 chars -> fully starred
    assert mask_description("abcdef") == "******"


def test_description_mask_is_idempotent() -> None:
    once = mask_description("ACME TRADING PTE LTD")
    assert mask_description(once) == once  # markers don't re-trigger


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
    assert "CITI BANK" not in str(txn)  # no counterparty name survives anywhere in the row


def test_strict_mode_fully_redacts_descriptions_for_real_statements() -> None:
    """strict=True (real/own statements): descriptions are fully redacted to ``**``, not
    first3***last3 — because first/last chars of a real name are still residual PII and
    must never enter git. Flow values + public security symbols are still kept."""
    masked = mask_extraction(
        {
            "institution": "DBS Bank",
            "transactions": [
                {"description": "FROM: WANG ZITIAN PAYNOW", "amount": "190.00", "direction": "IN", "balance_after": "42869.09"}
            ],
            "positions": [{"symbol": "AAPL", "quantity": "10", "market_value": "1900.25"}],
        },
        strict=True,
    )
    txn = masked["transactions"][0]
    assert txn["description"] == "**"  # fully redacted (not "FRO***NOW")
    assert "WANG" not in str(masked)
    assert txn["amount"] == "190.00" and txn["balance_after"] == "42869.09"  # flow kept
    assert masked["positions"][0]["symbol"] == "AAPL"  # public symbol kept
    assert masked["institution"] == "DBS Bank"  # institution name not PII


def test_flow_values_are_kept() -> None:
    """date / amount / direction / balance carry no identity PII and are preserved."""
    masked = mask_extraction(
        {"transactions": [{"date": "2024-01-01", "description": "ACME PTE LTD", "amount": "10.00", "direction": "OUT", "balance_after": "90.00"}]}
    )
    txn = masked["transactions"][0]
    assert txn["date"] == "2024-01-01"
    assert txn["amount"] == "10.00"
    assert txn["direction"] == "OUT"
    assert txn["balance_after"] == "90.00"
    assert txn["description"] == "ACM***LTD"


def test_mask_response_text_handles_fenced_json() -> None:
    out = mask_response_text('```json\n{"account_holder": "Jane Doe", "transactions": []}\n```')
    assert "Jane Doe" not in out
    assert "**" in out
    # non-JSON passes through unchanged
    assert mask_response_text("not json") == "not json"


def test_source_ref_url_vs_hash() -> None:
    assert source_ref(hf_url="https://hf/x.pdf") == {"origin": "huggingface", "url": "https://hf/x.pdf"}
    ref = source_ref(file_bytes=b"abc")
    assert ref["origin"] == "local" and len(ref["sha256"]) == 64

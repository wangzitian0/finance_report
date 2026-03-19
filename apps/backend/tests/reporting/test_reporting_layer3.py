"""EPIC-018 Phase 4: Tests for reporting Layer 3 integration."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from src.prompts.csv_mapping import build_csv_mapping_prompt
from src.prompts.reconciliation import RECONCILIATION_SEMANTIC_PROMPT, build_reconciliation_prompt


def test_csv_mapping_prompt_includes_headers():
    """CSV mapping prompt includes header and sample data."""
    headers = ["Date", "Description", "Amount"]
    sample_rows = [
        ["2025-01-15", "Coffee Shop", "25.00"],
        ["2025-01-16", "Salary", "3000.00"],
    ]

    prompt = build_csv_mapping_prompt(headers, sample_rows)
    assert "Date | Description | Amount" in prompt
    assert "Coffee Shop" in prompt
    assert "Salary" in prompt
    assert "Return your JSON mapping" in prompt


def test_csv_mapping_prompt_limits_sample_rows():
    """CSV mapping prompt limits to 5 sample rows."""
    headers = ["Date", "Desc"]
    sample_rows = [["row"] * 2 for _ in range(10)]

    prompt = build_csv_mapping_prompt(headers, sample_rows)
    # Should only contain 5 sample lines
    assert prompt.count("row | row") == 5


def test_reconciliation_prompt_includes_context():
    """Reconciliation prompt includes transaction and entry details."""
    prompt = build_reconciliation_prompt(
        txn_description="SALARY ACME CORP",
        entry_memo="Monthly payroll",
        date_diff_days=2,
        amount_match_pct=99.5,
    )

    assert "SALARY ACME CORP" in prompt
    assert "Monthly payroll" in prompt
    assert "2 days apart" in prompt
    assert "100%" in prompt or "99" in prompt
    assert "similarity_score" in prompt


def test_reconciliation_prompt_scoring_guidelines():
    """Reconciliation prompt includes scoring guidelines."""
    assert "90-100" in RECONCILIATION_SEMANTIC_PROMPT
    assert "70-89" in RECONCILIATION_SEMANTIC_PROMPT
    assert "50-69" in RECONCILIATION_SEMANTIC_PROMPT
    assert "0-49" in RECONCILIATION_SEMANTIC_PROMPT

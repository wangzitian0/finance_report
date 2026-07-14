"""Drift tests for the backend-owned API response conformance vectors (#1827).

Each test recomputes an endpoint's serialized response from the fixed
deterministic inputs in ``tools/api_response_vectors.py`` and compares it to
the committed ``common/<pkg>/conformance/vectors.json``. A serializer change
(field rename, type flip, alias, dropped default) without a vector
regeneration turns this red — the backend cannot silently change the wire
shape the frontend tests mock (G-contract-reddens).

Red-team demo (recorded in PR #1827): renaming a ``BalanceSheetResponse``
field without running ``tools/api_response_vectors.py`` reds
``test_AC_reporting_api_vectors_1_balance_sheet_matches_committed_vector``.
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.api_response_vectors import REPO_ROOT, build_vector_files


def _committed(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _vector_file(pkg: str) -> Path:
    return REPO_ROOT / "common" / pkg / "conformance" / "vectors.json"


def _regenerated(pkg: str) -> dict:
    files = build_vector_files()
    return files[_vector_file(pkg)]


def test_AC_reporting_api_vectors_1_balance_sheet_matches_committed_vector():
    """AC-reporting.api-vectors.1: the serialized GET /api/reports/balance-sheet
    response recomputed from fixed inputs equals the committed vector."""
    regenerated = _regenerated("reporting")
    committed = _committed(_vector_file("reporting"))
    assert regenerated == committed, (
        "GET /api/reports/balance-sheet wire shape drifted from the committed "
        "vector. If the serializer change is intentional, regenerate via "
        "`apps/backend/.venv/bin/python tools/api_response_vectors.py` and fix "
        "the failing frontend consumers of the new shape."
    )
    # Decimal red line on the wire: totals are 2dp strings, never JSON floats.
    response = committed["endpoints"]["balance_sheet"]["response"]
    for field in ("total_assets", "total_liabilities", "total_equity", "equation_delta"):
        assert isinstance(response[field], str), f"{field} must serialize as a decimal string"


def test_AC_ledger_api_vectors_1_accounts_list_matches_committed_vector():
    """AC-ledger.api-vectors.1: the serialized GET /api/accounts response
    recomputed from fixed inputs equals the committed vector."""
    regenerated = _regenerated("ledger")
    committed = _committed(_vector_file("ledger"))
    assert regenerated == committed, (
        "GET /api/accounts wire shape drifted from the committed vector. If "
        "intentional, regenerate via `apps/backend/.venv/bin/python "
        "tools/api_response_vectors.py` and fix the failing frontend consumers."
    )
    response = committed["endpoints"]["accounts_list"]["response"]
    assert response["total"] == len(response["items"])
    for item in response["items"]:
        if item["balance"] is not None:
            assert isinstance(item["balance"], str), "balance must serialize as a decimal string"


def test_AC_extraction_api_vectors_1_statement_upload_matches_committed_vector():
    """AC-extraction.api-vectors.1: the serialized statement upload/status
    responses recomputed from fixed inputs equal the committed vector."""
    regenerated = _regenerated("extraction")
    committed = _committed(_vector_file("extraction"))
    assert regenerated == committed, (
        "POST /api/statements/upload / GET /api/statements/{id} wire shape "
        "drifted from the committed vector. If intentional, regenerate via "
        "`apps/backend/.venv/bin/python tools/api_response_vectors.py` and fix "
        "the failing frontend consumers."
    )
    parsed = committed["endpoints"]["statement_parsed"]["response"]
    # The parsed vector must stay internally consistent with the balance
    # validation semantics it advertises: open + sum(IN) - sum(OUT) == close.
    from decimal import Decimal

    delta = sum(
        (Decimal(t["amount"]) if t["direction"] == "IN" else -Decimal(t["amount"])) for t in parsed["transactions"]
    )
    assert Decimal(parsed["opening_balance"]) + delta == Decimal(parsed["closing_balance"])
    assert parsed["balance_validated"] is True

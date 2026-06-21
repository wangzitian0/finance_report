"""No-LLM seeded statement journey (EPIC-008 / AC8.21).

These E2E tests exercise the statement review -> reconcile -> report journey for
an **already-parsed** statement that was injected by the ``seeded_parsed_statement``
fixture — never by a real provider. They carry only ``@pytest.mark.e2e`` (no
``@pytest.mark.llm``), so they run in the merge-blocking no-LLM tier
(``pr-test.yml`` / ``ci.yml backend-e2e-tier1``: ``-m "... and not llm"``).

The point these prove that the legacy ``@pytest.mark.llm`` mega-journeys could not:
the DOM/CRUD/render assertions on a parsed statement (list row link text, detail
fields, transactions, report numbers) run pre-merge with zero provider cost, so a
selector/contract drift fails CI at PR time instead of slipping to staging.
"""

from decimal import Decimal

import pytest

from tests.e2e.conftest import SeededParsedStatement


@pytest.mark.e2e
async def test_seeded_fixture_bypasses_provider(seeded_parsed_statement: SeededParsedStatement):
    """EPIC-008 / AC8.21.1: the seeded fixture materializes a parsed statement with no provider call.

    GIVEN the ``seeded_parsed_statement`` fixture
    WHEN it builds the layered records
    THEN a PARSED statement with linked ODS document and atomic transactions exists,
    with a non-empty ``original_filename`` and Decimal balances — proving the LLM/OCR
    extraction seam was bypassed entirely.
    """
    seeded = seeded_parsed_statement
    assert seeded.statement.status.value == "parsed"
    assert seeded.statement.uploaded_document_id == seeded.document.id
    # The #1142 invisible-link field: a parsed statement must carry a visible filename.
    assert seeded.original_filename
    assert len(seeded.transactions) >= 1
    # Monetary red line: balances are Decimal, never float.
    assert isinstance(seeded.statement.opening_balance, Decimal)
    assert isinstance(seeded.statement.closing_balance, Decimal)


@pytest.mark.e2e
async def test_seeded_statement_list_and_detail_no_llm(client, seeded_parsed_statement: SeededParsedStatement):
    """EPIC-008 / AC8.21.2: a seeded parsed statement renders through list -> detail with no provider.

    GIVEN a fixture-seeded parsed statement (no LLM)
    WHEN listing statements and fetching the statement by id via the real API
    THEN the list row and detail expose ``status=parsed``, a non-empty
    ``original_filename`` (the stretched-link row label, #1142), and the parsed
    transactions — the exact assertions that were previously buried in an
    ``@pytest.mark.llm`` mega-journey.
    """
    seeded = seeded_parsed_statement

    list_resp = await client.get("/statements")
    assert list_resp.status_code == 200, list_resp.text
    items = list_resp.json()["items"]
    row = next((it for it in items if it["id"] == str(seeded.id)), None)
    assert row is not None, "seeded statement must appear in the list"
    assert row["status"] == "parsed"
    # #1142: the list row link renders ``original_filename``; a parsed statement
    # must expose a non-empty value so the row link is never invisible/zero-size.
    assert row["original_filename"] == seeded.original_filename
    assert row["original_filename"] != ""

    detail_resp = await client.get(f"/statements/{seeded.id}")
    assert detail_resp.status_code == 200, detail_resp.text
    detail = detail_resp.json()
    assert detail["id"] == str(seeded.id)
    assert detail["status"] == "parsed"
    assert detail["institution"] == seeded.statement.institution
    assert detail["original_filename"] == seeded.original_filename
    # The parsed transactions resolve via source_documents -> uploaded_document_id.
    assert len(detail["transactions"]) == len(seeded.transactions)


@pytest.mark.e2e
async def test_seeded_statement_transactions_endpoint_no_llm(client, seeded_parsed_statement: SeededParsedStatement):
    """EPIC-008 / AC8.21.3: the seeded statement's transactions list resolves with no provider.

    GIVEN a fixture-seeded parsed statement (no LLM)
    WHEN requesting its transactions endpoint
    THEN the parsed atomic transactions are returned with their Decimal amounts and
    directions — the downstream review/reconcile journey runs without any extraction call.
    """
    seeded = seeded_parsed_statement

    resp = await client.get(f"/statements/{seeded.id}/transactions")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == len(seeded.transactions)

    returned_descriptions = {item["description"] for item in items}
    expected_descriptions = {txn.description for txn in seeded.transactions}
    assert returned_descriptions == expected_descriptions

    # Amounts round-trip as Decimal-safe strings (monetary red line).
    for item in items:
        assert Decimal(str(item["amount"])) > Decimal("0")
        assert item["direction"] in {"IN", "OUT"}

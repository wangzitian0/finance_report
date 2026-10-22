"""GET /statements list budget (#2583 S4).

The list endpoint feeds Home, /attention and the /upload poll. It must issue a
bounded number of SQL statements and must not embed transactions.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event

from src.extraction import DocumentType, UploadedDocument
from src.extraction.orm.statement_summary import StatementSummary
from src.identity import User
from tests.factories import seed_parsed_statement

pytestmark = pytest.mark.asyncio

ROWS_PER_STATEMENT = 2


async def _seed_statements(db, user_id, count: int, *, name_prefix: str = "list_budget"):
    seeded = []
    for index in range(count):
        seeded.append(
            await seed_parsed_statement(
                db,
                user_id,
                institution="DBS",
                original_filename=f"{name_prefix}_{index:02d}.pdf",
                opening_balance=Decimal("1000.00"),
            )
        )
    await db.commit()
    return seeded


async def _count_sql(db_engine, client, path: str, params: dict | None = None):
    statements: list[str] = []

    def capture(_conn, _cursor, statement_text, _parameters, _context, _executemany):
        statements.append(statement_text)

    event.listen(db_engine.sync_engine, "before_cursor_execute", capture)
    try:
        response = await client.get(path, params=params)
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    return response, statements


async def test_AC_extraction_statement_list_1_sql_count_does_not_grow_with_statement_count(
    client, db, db_engine, test_user
):
    """AC-extraction.statement-list.1: the list issues the same number of SQL statements for 3 and for 12 statements."""
    await _seed_statements(db, test_user.id, 3)
    small_response, small_sql = await _count_sql(db_engine, client, "/statements")
    assert small_response.json()["total"] == 3

    await _seed_statements(db, test_user.id, 9, name_prefix="list_budget_more")
    large_response, large_sql = await _count_sql(db_engine, client, "/statements")
    assert large_response.json()["total"] == 12
    assert len(large_response.json()["items"]) == 12

    assert len(large_sql) == len(small_sql), (
        f"SQL count grew with statement count: 3 statements -> {len(small_sql)}, 12 statements -> {len(large_sql)}"
    )
    assert len(large_sql) <= 8, f"expected a bounded list, got {len(large_sql)} SQL statements"


async def test_AC_extraction_statement_list_2_list_has_no_transactions_option(
    client, db, db_engine, test_user, openapi_schema
):
    """AC-extraction.statement-list.2: the list has no include_transactions option and every item has an empty transactions list."""
    seeded = await _seed_statements(db, test_user.id, 3)
    assert all(len(item.transactions) == ROWS_PER_STATEMENT for item in seeded)

    parameters = openapi_schema["paths"]["/statements"]["get"].get("parameters", [])
    assert "include_transactions" not in {parameter["name"] for parameter in parameters}

    default_response, default_sql = await _count_sql(db_engine, client, "/statements")
    default_items = default_response.json()["items"]
    assert len(default_items) == 3
    assert all(item["transactions"] == [] for item in default_items)
    # The envelope fields stay complete so the page can still render a row.
    assert {item["original_filename"] for item in default_items} == {f"list_budget_{i:02d}.pdf" for i in range(3)}
    assert all(item["file_path"] for item in default_items)

    # A caller that still sends the removed option gets the same lean answer with the same SQL count.
    ignored_response, ignored_sql = await _count_sql(
        db_engine, client, "/statements", params={"include_transactions": "true"}
    )
    ignored_items = ignored_response.json()["items"]
    assert len(ignored_items) == 3
    assert all(item["transactions"] == [] for item in ignored_items)
    assert len(ignored_sql) == len(default_sql)


async def test_AC_extraction_statement_list_3_document_lookup_keeps_user_isolation_and_hash_fallback(
    client, db, db_engine, test_user
):
    """AC-extraction.statement-list.3: batched document lookup ignores another user's document and falls back to the file hash."""
    seeded = await _seed_statements(db, test_user.id, 2)
    linked, unlinked = seeded[0], seeded[1]

    # Statement 1 loses its document link; the shared (user_id, file_hash) key must still resolve it.
    unlinked_statement = await db.get(StatementSummary, unlinked.id)
    unlinked_statement.uploaded_document_id = None

    # Statement 0 points at a document owned by another user; that document must never be returned.
    other_user = User(
        id=uuid4(),
        email=f"other_{uuid4().hex[:8]}@example.com",
        name="Other User",
        hashed_password="test_hashed_password",
    )
    db.add(other_user)
    await db.flush()
    foreign_document = UploadedDocument(
        id=uuid4(),
        user_id=other_user.id,
        file_path="foreign/path.pdf",
        file_hash=uuid4().hex + uuid4().hex[:32],
        original_filename="foreign.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(foreign_document)
    await db.flush()
    linked_statement = await db.get(StatementSummary, linked.id)
    linked_statement.uploaded_document_id = foreign_document.id
    await db.commit()

    response, _ = await _count_sql(db_engine, client, "/statements")
    by_id = {item["id"]: item for item in response.json()["items"]}

    assert by_id[str(unlinked.id)]["original_filename"] == "list_budget_01.pdf"
    assert by_id[str(linked.id)]["original_filename"] != "foreign.pdf"
    assert by_id[str(linked.id)]["file_path"] != "foreign/path.pdf"

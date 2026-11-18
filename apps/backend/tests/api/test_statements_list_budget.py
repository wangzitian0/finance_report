from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event

from src.extraction import DocumentType, UploadedDocument
from src.extraction.orm.statement_summary import StatementSummary
from tests.factories import UserFactory, seed_parsed_statement

pytestmark = pytest.mark.asyncio
ROWS_PER_STATEMENT = 2


async def _seed_statements(db, user_id, count: int, *, name_prefix: str = "list_budget"):
    seeded = [
        await seed_parsed_statement(
            db,
            user_id,
            institution="DBS",
            original_filename=f"{name_prefix}_{i:02d}.pdf",
            opening_balance=Decimal("1000.00"),
        )
        for i in range(count)
    ]
    await db.commit()
    return seeded


async def _count_sql(db_engine, client, path: str, params: dict | None = None):
    stmts: list[str] = []
    capture = lambda _c, _cur, text, *_a: stmts.append(text)
    event.listen(db_engine.sync_engine, "before_cursor_execute", capture)
    try:
        resp = await client.get(path, params=params)
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", capture)
    assert resp.status_code == 200, resp.text
    return resp, stmts


async def test_AC_extraction_statement_list_1_sql_count_does_not_grow_with_statement_count(
    client, db, db_engine, test_user
):
    await _seed_statements(db, test_user.id, 3)
    small_resp, small_sql = await _count_sql(db_engine, client, "/statements")
    await _seed_statements(db, test_user.id, 9, name_prefix="list_budget_more")
    large_resp, large_sql = await _count_sql(db_engine, client, "/statements")
    assert (small_resp.json()["total"], large_resp.json()["total"], len(large_resp.json()["items"])) == (3, 12, 12)
    assert len(large_sql) == len(small_sql) <= 8


async def test_AC_extraction_statement_list_2_list_has_no_transactions_option(
    client, db, db_engine, test_user, openapi_schema
):
    seeded = await _seed_statements(db, test_user.id, 3)
    assert all(len(i.transactions) == ROWS_PER_STATEMENT for i in seeded)
    assert "include_transactions" not in {
        p["name"] for p in openapi_schema["paths"]["/statements"]["get"].get("parameters", [])
    }
    assert "transactions" not in openapi_schema["components"]["schemas"]["BankStatementListItemResponse"]["properties"]
    assert (
        openapi_schema["components"]["schemas"]["ListResponse_BankStatementListItemResponse_"]["properties"]["items"][
            "items"
        ]["$ref"]
        == "#/components/schemas/BankStatementListItemResponse"
    )

    default_resp, default_sql = await _count_sql(db_engine, client, "/statements")
    ignored_resp, ignored_sql = await _count_sql(
        db_engine, client, "/statements", params={"include_transactions": "true"}
    )
    pending_resp, _ = await _count_sql(db_engine, client, "/statements/pending-review")
    assert len(ignored_sql) == len(default_sql)
    for items in (default_resp.json()["items"], ignored_resp.json()["items"], pending_resp.json()["items"]):
        assert len(items) == 3 and all("transactions" not in i for i in items)
    assert {i["original_filename"] for i in default_resp.json()["items"]} == {
        f"list_budget_{i:02d}.pdf" for i in range(3)
    }
    assert all(i["file_path"] for i in default_resp.json()["items"])


async def test_AC_extraction_statement_list_3_document_lookup_keeps_user_isolation_and_hash_fallback(
    client, db, db_engine, test_user
):
    linked, unlinked = await _seed_statements(db, test_user.id, 2)
    (await db.get(StatementSummary, unlinked.id)).uploaded_document_id = None
    other = await UserFactory.create_async(db)
    foreign_doc = UploadedDocument(
        id=uuid4(),
        user_id=other.id,
        file_path="foreign/path.pdf",
        file_hash=uuid4().hex + uuid4().hex[:32],
        original_filename="foreign.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(foreign_doc)
    await db.flush()
    (await db.get(StatementSummary, linked.id)).uploaded_document_id = foreign_doc.id
    await db.commit()
    resp, _ = await _count_sql(db_engine, client, "/statements")
    by_id = {i["id"]: i for i in resp.json()["items"]}
    assert by_id[str(unlinked.id)]["original_filename"] == "list_budget_01.pdf"
    assert (
        by_id[str(linked.id)]["original_filename"] != "foreign.pdf"
        and by_id[str(linked.id)]["file_path"] != "foreign/path.pdf"
    )

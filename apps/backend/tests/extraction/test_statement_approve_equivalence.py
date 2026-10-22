"""Approving a statement writes the same state as before the #2612 change.

The golden file holds the state that ``main`` at ``bba3aa84`` wrote for the same fixture. The fixture
approves two statements through ``POST /statements/{id}/review/approve`` and reads the reports. The
snapshot covers every table that holds rows. It labels each identifier by its meaning (an account
name, a transaction description, an entry memo) so that two runs compare equal although the
database generates new identifiers. It masks timestamps and digests that hash an identifier.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import Base
from src.extraction import TransactionDirection
from tests.e2e.test_statement_corpus_journeys import attach_reviewed_corpus_semantics
from tests.factories import seed_parsed_statement

pytestmark = pytest.mark.asyncio

GOLDEN_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "statement_approve_state_golden.json"

_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_HEX_RE = re.compile(r"\b[0-9a-f]{32,64}\b")
_DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?")

# Columns that hold the time of the run or a counter of the database.
_VOLATILE_COLUMNS = {"created_at", "updated_at", "stage1_reviewed_at", "occurred_at"}


def _statement_rows(offset: int, names: list[str]) -> list[dict]:
    """Rows with in and out movements. Every description is unique, so a label names one row."""
    start = date(2026, 1, 1) + timedelta(days=offset)
    rows = []
    for index, name in enumerate(names):
        incoming = name.startswith("Salary") or name.startswith("Refund")
        rows.append(
            {
                "description": name,
                "amount": Decimal("2500.00") + index if incoming else Decimal("12.50") + Decimal(index) * 3,
                "direction": TransactionDirection.IN if incoming else TransactionDirection.OUT,
                "date": start + timedelta(days=index),
            }
        )
    return rows


async def _approve(
    client, db: AsyncSession, user_id: UUID, *, filename: str, last4: str, offset: int, names: list[str]
) -> str:
    rows = _statement_rows(offset, names)
    seeded = await seed_parsed_statement(
        db,
        user_id,
        institution="DBS",
        original_filename=filename,
        opening_balance=Decimal("1000.00"),
        transactions=rows,
    )
    # The factories count in the process. Fixed values keep the snapshot equal in any test order.
    seeded.document.file_path = f"statements/{filename}"
    seeded.statement.account_last4 = last4
    seeded.statement.period_start = rows[0]["date"]
    seeded.statement.period_end = rows[-1]["date"]
    await attach_reviewed_corpus_semantics(db, user_id, seeded.transactions)
    await db.commit()
    statement_id = str(seeded.id)
    review = await client.get(f"/statements/{statement_id}/review")
    assert review.status_code == 200, review.text
    response = await client.post(f"/statements/{statement_id}/review/approve", json={"create_account_if_missing": True})
    assert response.status_code == 200, response.text
    assert response.json()["journal_entries_created"] == len(names)
    return statement_id


async def _rows_of(db: AsyncSession, table: str) -> list[dict[str, Any]]:
    result = await db.execute(text(f'SELECT * FROM "{table}"'))
    return [dict(row) for row in result.mappings().all()]


def _tokens(rows_by_table: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    """Map every identifier that names one thing to a label that states the thing."""
    tokens: dict[str, str] = {}

    def add(value: Any, label: str) -> None:
        if value is not None:
            tokens[str(value)] = label

    for row in rows_by_table.get("users", []):
        add(row["id"], "user")
    accounts = {row["id"]: f"account:{row['name']}" for row in rows_by_table.get("accounts", [])}
    for key, label in accounts.items():
        add(key, label)
    for row in rows_by_table.get("uploaded_documents", []):
        add(row["id"], f"document:{row['original_filename']}")
        add(row["file_hash"], f"hash:{row['original_filename']}")
    documents = {row["id"]: row["original_filename"] for row in rows_by_table.get("uploaded_documents", [])}
    for row in rows_by_table.get("statement_summaries", []):
        name = documents.get(row["uploaded_document_id"], str(row["period_start"]))
        add(row["id"], f"statement:{name}")
    for row in rows_by_table.get("atomic_transactions", []):
        add(row["id"], f"transaction:{row['description']}")
    entries = {row["id"]: row for row in rows_by_table.get("journal_entries", [])}
    for key, row in entries.items():
        add(key, f"entry:{row['memo']}@{row['entry_date']}")
    for row in rows_by_table.get("journal_lines", []):
        entry = entries[row["journal_entry_id"]]
        add(row["id"], f"line:{entry['memo']}@{entry['entry_date']}:{row['line_no']}")
    # A journal command target names the entry that it authorizes.
    records = {row["id"]: row for row in rows_by_table.get("trace_records", [])}
    for key, row in entries.items():
        anchor = records.get(row["decision_anchor_id"])
        if anchor is not None:
            add(anchor["target_id"], f"command:{row['memo']}@{row['entry_date']}")
    for key, row in records.items():
        target = tokens.get(str(row["target_id"]), "<target>")
        add(key, f"trace:{row['record_type']}:{row['assertion_kind']}/{row['assertion_id']}@{target}")
    nodes = {}
    for row in rows_by_table.get("evidence_nodes", []):
        entity = tokens.get(str(row["entity_id"]), "<entity>")
        label = f"node:{row['node_kind']}:{row['entity_type']}:{entity}"
        nodes[row["id"]] = label
        add(row["id"], label)
    return tokens


def _normalize(value: Any, tokens: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _normalize(item, tokens) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_normalize(item, tokens) for item in value]
    if isinstance(value, datetime):
        return "<datetime>"
    if isinstance(value, UUID | str):
        text_value = str(value)
        for token in sorted(tokens, key=len, reverse=True):
            if token in text_value:
                text_value = text_value.replace(token, tokens[token])
        text_value = _UUID_RE.sub("<uuid>", text_value)
        text_value = _DATETIME_RE.sub("<datetime>", text_value)
        return _HEX_RE.sub("<hex>", text_value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes | bytearray | memoryview):
        return "<bytes>"
    return value


async def snapshot_state(db: AsyncSession) -> dict[str, list[dict[str, Any]]]:
    """Return every row of every table that holds rows, with identifiers labelled by meaning."""
    rows_by_table: dict[str, list[dict[str, Any]]] = {}
    for table in Base.metadata.sorted_tables:
        rows = await _rows_of(db, table.name)
        if rows:
            rows_by_table[table.name] = rows
    tokens = _tokens(rows_by_table)
    snapshot: dict[str, list[dict[str, Any]]] = {}
    for table_name, rows in rows_by_table.items():
        normalized = []
        for row in rows:
            clean = {key: value for key, value in row.items() if key not in _VOLATILE_COLUMNS}
            normalized.append(_normalize(clean, tokens))
        normalized.sort(key=lambda item: json.dumps(item, sort_keys=True, default=str))
        snapshot[table_name] = normalized
    return json.loads(json.dumps(snapshot, sort_keys=True, default=str))


async def build_approved_state(client, db: AsyncSession, user_id: UUID) -> dict[str, Any]:
    await _approve(
        client,
        db,
        user_id,
        filename="approve_equivalence_jan.pdf",
        last4="1001",
        offset=0,
        names=["Salary January", "Rent January", "Groceries A", "Groceries B", "Transit pass", "Refund shop"],
    )
    await _approve(
        client,
        db,
        user_id,
        filename="approve_equivalence_feb.pdf",
        last4="1002",
        offset=40,
        names=["Salary February", "Rent February", "Dentist", "Books"],
    )
    reports = {}
    balance = await client.get("/reports/balance-sheet", params={"as_of_date": "2026-03-31", "currency": "SGD"})
    assert balance.status_code == 200, balance.text
    income = await client.get(
        "/reports/income-statement",
        params={"start_date": "2026-01-01", "end_date": "2026-03-31", "currency": "SGD"},
    )
    assert income.status_code == 200, income.text
    tokens: dict[str, str] = {}
    for table in ("accounts",):
        for row in await _rows_of(db, table):
            tokens[str(row["id"])] = f"account:{row['name']}"
    reports["balance_sheet"] = _normalize(balance.json(), tokens)
    reports["income_statement"] = _normalize(income.json(), tokens)
    return {"tables": await snapshot_state(db), "reports": reports}


def format_golden(state: dict[str, Any]) -> str:
    """One row per line, so that a review reads a change as a line diff."""
    lines = ["{", '"reports": ' + json.dumps(state["reports"], sort_keys=True) + ",", '"tables": {']
    tables = sorted(state["tables"].items())
    for index, (name, rows) in enumerate(tables):
        lines.append(f"{json.dumps(name)}: [")
        lines.extend(json.dumps(row, sort_keys=True) + ("," if i < len(rows) - 1 else "") for i, row in enumerate(rows))
        lines.append("]" + ("," if index < len(tables) - 1 else ""))
    lines.extend(["}", "}"])
    return "\n".join(lines) + "\n"


async def test_AC_extraction_statement_approve_1_state_equals_the_pre_change_golden(
    client, db: AsyncSession, test_user
) -> None:
    """AC-extraction.statement-approve.1: approving two statements writes the journal entries, lines,
    decision anchors, trace graph, evidence graph and report values that ``main`` at ``bba3aa84`` wrote."""
    state = await build_approved_state(client, db, test_user.id)
    golden = json.loads(GOLDEN_PATH.read_text())

    # The fixture covers what the golden must hold. An empty golden would pass a broken change.
    assert len(state["tables"]["journal_entries"]) == 10 + 2  # ten statement rows, two opening balances
    assert len(state["tables"]["journal_lines"]) == 24
    assert len(state["tables"]["trace_records"]) == 10 * 7 + 2 * 4
    assert state["tables"]["trace_record_parents"], "the trace graph holds parent links"
    assert state["reports"]["balance_sheet"]["total_assets"] != "0.00"
    assert state == golden

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from src.extraction import ClassificationStatus, RuleType, TransactionDirection
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.ledger import AccountType
from tests.factories import AccountFactory, seed_parsed_statement

pytestmark = [pytest.mark.integration, pytest.mark.e2e]
CASSETTE_DIR = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "llm_cassettes"

CORPUS_FINGERPRINTS: tuple[str, ...] = (
    "d69fbafcecb481e614651b1178a5fb9d9e3724718ef7bf623502120bcd27db30",
    "cb5dd1f714784190dab3356c17d635a0e09b8f9fca78abb6023218ca29efcbab",
    "05d7858b5baa76e92d75f39b2c7d101d16aac776c608488affc21a14c1f754c1",
    "61dcbca67c96bb5371188772a290d30d868be8c2ed4533352b4c4bb8a44fc046",
    "25e00d6718d89f0fe44dc9acf4333649bbfa467780422ef2c6b9db322d96ea21",
    "a531a974fd0bd144fd4a31f63d94384210f043c94bfc81631b20d3f178c779ed",
    "f480cf4eb7050d96a674f2ff45fe92c1bad7920ff26df9c754469e40db64b219",
    "e3dd21a7fe486770b51b39f51f49738221e4236fcbfb9e2d3b1f0c27030daf37",
    "ccd2975934705a6e8b0d04ea97879fd4d8ca8f1a093216fb2149ddbba6aafc9a",
    "4ec965fd2615a4b285964aab735b385feae08fc754282629b39101ae12083efe",
)
ZERO_TXN_FINGERPRINT = "05d7858b5baa76e92d75f39b2c7d101d16aac776c608488affc21a14c1f754c1"
MULTI_STATEMENT_FINGERPRINTS = CORPUS_FINGERPRINTS[3:6]


@dataclass(frozen=True)
class CorpusCase:
    fingerprint: str
    modality: str
    institution_class: str
    edge_condition: str
    institution: str
    opening_balance: Decimal
    rows: tuple[dict, ...]
    unpostable_rows: int

    @property
    def short_id(self) -> str:
        return self.fingerprint[:8]

    @property
    def net_movement(self) -> Decimal:
        return sum(
            (r["amount"] if r["direction"] == TransactionDirection.IN else -r["amount"] for r in self.rows),
            Decimal("0"),
        )


def load_corpus_case(fingerprint: str) -> CorpusCase:
    cassette = json.loads((CASSETTE_DIR / f"{fingerprint}.json").read_text())
    out = Path(__file__).resolve().parents[2] / "test-results"
    out.mkdir(exist_ok=True)
    with (out / f"served-cassettes-{os.getpid()}.txt").open("a", encoding="utf-8") as fh:
        fh.write(f"{fingerprint}\n")
    truth = json.loads((CASSETTE_DIR / "ground_truth" / f"{fingerprint}.truth.json").read_text())
    payload = json.loads(cassette["response"]["stream_text"])
    rows, unpostable = [], 0
    for index, txn in enumerate(payload["transactions"]):
        if txn["amount"] is None or Decimal(str(txn["amount"])) == 0:
            unpostable += 1
            continue
        amount = Decimal(str(txn["amount"]))
        raw_dir = str(txn.get("direction", "IN" if amount >= 0 else "OUT")).upper()
        if raw_dir not in ("IN", "OUT"):
            raise ValueError(f"{fingerprint[:8]}: unknown direction {txn['direction']!r} in cassette row {index}")
        rows.append(
            {
                "description": txn["description"] or f"corpus txn {index}",
                "amount": abs(amount),
                "direction": TransactionDirection(raw_dir),
                "date": date.fromisoformat(txn["date"]),
            }
        )
    return CorpusCase(
        fingerprint=fingerprint,
        modality=truth["modality"],
        institution_class=truth["institution_class"],
        edge_condition=truth["edge_condition"],
        institution=payload.get("institution") or truth["institution_class"].title(),
        opening_balance=Decimal(str(payload["opening_balance"])),
        rows=tuple(rows),
        unpostable_rows=unpostable,
    )


async def attach_reviewed_corpus_semantics(db, user_id, transactions: list[AtomicTransaction]) -> None:
    if not transactions:
        return
    currency, base_date, suffix = transactions[0].currency, min(t.txn_date for t in transactions), uuid4()
    rules = {}
    for direction, acc_type, cat in (
        (TransactionDirection.IN, AccountType.INCOME, "CORPUS_REVIEWED_INCOME"),
        (TransactionDirection.OUT, AccountType.EXPENSE, "CORPUS_REVIEWED_EXPENSE"),
    ):
        acc = await AccountFactory.create_async(
            db, user_id=user_id, name=f"{acc_type.value.title()} - Corpus Reviewed", type=acc_type, currency=currency
        )
        rules[direction] = ClassificationRule(
            user_id=user_id,
            created_by=user_id,
            version_number=1,
            effective_date=base_date,
            is_active=False,
            rule_name=f"corpus-{direction.value}-{suffix}",
            rule_type=RuleType.KEYWORD_MATCH,
            rule_config={"keywords": []},
            tag_mappings={"category": cat, "rationale": "corpus reviewer confirmation"},
            default_account_id=acc.id,
        )
    db.add_all(rules.values())
    await db.flush()
    db.add_all(
        [
            TransactionClassification(
                atomic_txn_id=t.id,
                rule_version_id=rules[t.direction].id,
                account_id=rules[t.direction].default_account_id,
                tags={
                    "category": "CORPUS_REVIEWED_INCOME"
                    if t.direction is TransactionDirection.IN
                    else "CORPUS_REVIEWED_EXPENSE",
                    "rationale": "corpus reviewer confirmation",
                },
                confidence_score=100,
                status=ClassificationStatus.APPLIED,
            )
            for t in transactions
        ]
    )
    await db.commit()


async def _seed_and_accept_case(client, db, user_id, case: CorpusCase, prefix: str) -> str:
    seeded = await seed_parsed_statement(
        db,
        user_id,
        institution=case.institution,
        original_filename=f"{prefix}_{case.short_id}.pdf",
        opening_balance=case.opening_balance,
        transactions=[dict(r) for r in case.rows],
    )
    if case.rows:
        seeded.statement.period_start, seeded.statement.period_end = (
            min(r["date"] for r in case.rows),
            max(r["date"] for r in case.rows),
        )
    await attach_reviewed_corpus_semantics(db, user_id, seeded.transactions)
    stmt_id = str(seeded.id)
    review_resp = await client.get(f"/statements/{stmt_id}/review")
    assert (
        review_resp.status_code == 200
        and len(review_resp.json()["transactions"]) == len(case.rows)
        and review_resp.json()["balance_validation_result"]["closing_match"] is True
    )
    conflicts = (await client.get(f"/statements/{stmt_id}/conflicts")).json()
    if conflicts["duplicates"] or conflicts["transfer_pairs"]:
        assert (
            await client.post(
                f"/statements/{stmt_id}/conflict-resolutions",
                json={"action": "confirm_distinct", "note": f"corpus {case.short_id}: source rows verified"},
            )
        ).status_code == 200
    approve_resp = await client.post(f"/statements/{stmt_id}/approvals", json={"create_account_if_missing": True})
    assert (
        approve_resp.status_code == 200
        and approve_resp.json()["journal_entries_created"] == len(case.rows)
        and approve_resp.json()["account_id"]
    )
    run_resp = await client.post("/reconciliation/runs", json={"statement_id": stmt_id})
    assert run_resp.status_code == 200 and run_resp.json()["unmatched"] == 0
    return approve_resp.json()["account_id"]


@pytest.mark.e2e
def test_corpus_manifest_is_diverse():
    assert len(CORPUS_FINGERPRINTS) == len(set(CORPUS_FINGERPRINTS)) == 10
    cases = [load_corpus_case(fp) for fp in CORPUS_FINGERPRINTS]
    assert (
        {c.modality for c in cases} == {"text", "vision"}
        and {"bank", "brokerage"} <= {c.institution_class for c in cases}
        and "duplicate_rows" in {c.edge_condition for c in cases}
    )
    txn_counts = sorted(len(c.rows) for c in cases)
    assert txn_counts[0] == 0 and sum(1 for n in txn_counts if n >= 150) >= 3
    assert (
        all(
            isinstance(r["amount"], Decimal) and r["direction"] in (TransactionDirection.IN, TransactionDirection.OUT)
            for c in cases
            for r in c.rows
        )
        and {c.fingerprint: c.unpostable_rows for c in cases if c.unpostable_rows} == {}
    )


@pytest.mark.e2e
@pytest.mark.parametrize("fingerprint", CORPUS_FINGERPRINTS, ids=lambda fp: fp[:8])
async def test_corpus_statement_full_journey(client, db, test_user, fingerprint):
    case = load_corpus_case(fingerprint)
    account_id = await _seed_and_accept_case(client, db, test_user.id, case, "corpus")
    assert (report := (await client.get("/reports/balance-sheet")).json())["is_balanced"] is True
    if not case.rows:
        return
    assert {line["account_id"]: Decimal(str(line["amount"])) for line in report["assets"]}[
        account_id
    ] == case.opening_balance + case.net_movement
    p_start, p_end = min(r["date"] for r in case.rows).isoformat(), max(r["date"] for r in case.rows).isoformat()
    income = (await client.get("/reports/income-statement", params={"start_date": p_start, "end_date": p_end})).json()
    assert (
        Decimal(str(income["total_income"])) - Decimal(str(income["total_expenses"])),
        Decimal(str(income["net_income"])),
    ) == (case.net_movement, case.net_movement)
    cf = (await client.get("/reports/cash-flow", params={"start_date": p_start, "end_date": p_end})).json()
    activity = next(
        (i for sec in ("operating", "investing", "financing") for i in cf[sec] if i.get("account_id") == account_id),
        None,
    )
    assert activity is None, (
        f"[{case.short_id}] cash custody account must not appear as a non-cash activity line: {activity}"
    )
    assert (Decimal(str(cf["summary"]["beginning_cash"])), Decimal(str(cf["summary"]["ending_cash"]))) == (
        case.opening_balance,
        case.opening_balance + case.net_movement,
    )


@pytest.mark.e2e
async def test_corpus_multi_statement_acceptance_same_user(client, db, test_user):
    cases = [load_corpus_case(fp) for fp in MULTI_STATEMENT_FINGERPRINTS]
    account_ids = [await _seed_and_accept_case(client, db, test_user.id, case, "corpus_multi") for case in cases]
    all_dates, expected_total = (
        [r["date"] for c in cases for r in c.rows],
        sum((c.net_movement for c in cases), Decimal("0")),
    )
    balance = (await client.get("/reports/balance-sheet")).json()
    assert (
        len(set(account_ids)) == 3
        and balance["is_balanced"] is True
        and sum(
            (
                {line["account_id"]: Decimal(str(line["amount"])) for line in balance["assets"]}[aid]
                for aid in account_ids
            ),
            Decimal("0"),
        )
        == sum((c.opening_balance for c in cases), expected_total)
    )
    income = (
        await client.get(
            "/reports/income-statement",
            params={"start_date": min(all_dates).isoformat(), "end_date": max(all_dates).isoformat()},
        )
    ).json()
    assert (
        Decimal(str(income["total_income"])) - Decimal(str(income["total_expenses"])),
        Decimal(str(income["net_income"])),
    ) == (expected_total, expected_total)

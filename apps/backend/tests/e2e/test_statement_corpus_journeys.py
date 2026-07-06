"""Extraction-corpus journeys in the merge tier (llm package roadmap, AC-llm.11).

The committed LLM cassettes under ``common/testing/fixtures/llm_cassettes/``
are the repo's extraction artifacts: each one freezes a real GLM extraction
output (``response.stream_text``) whose field accuracy is already graded
against a sibling ``ground_truth/*.truth.json`` at extraction-unit level
(AC23.7/AC23.8). Before AC-llm.11 that corpus never reached the E2E chain — the
merge tier proved review → reconcile → report on one synthetic fixture.

These tests seed a 10-cassette diverse corpus through ``seed_parsed_statement``
(the AC8.21 provider-free seam) and drive each statement through the full
downstream journey via the real API. The cassette's frozen extraction output is
the seed source — not the truth file — because only the extraction output
carries ``direction``; the truth files record unsigned magnitudes.

Provider cost: zero. Tests carry only ``@pytest.mark.e2e`` (never ``llm``) and
run in ``ci.yml backend-e2e-tier1``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from common.testing.ac_proof import ac_proof

from src.models.layer2 import TransactionDirection
from tests.factories import seed_parsed_statement

REPO_ROOT = Path(__file__).resolve().parents[4]
CASSETTE_DIR = REPO_ROOT / "common" / "testing" / "fixtures" / "llm_cassettes"
GROUND_TRUTH_DIR = CASSETTE_DIR / "ground_truth"

# ---------------------------------------------------------------------------
# The corpus manifest (AC-llm.11.1). 10 maximally-diverse fingerprints, chosen for
# axis coverage rather than volume — the diversity invariants are asserted by
# test_corpus_manifest_is_diverse so the set cannot silently shrink or
# homogenize. Registered in common/llm/contract.py roadmap group 10.
# ---------------------------------------------------------------------------
CORPUS_FINGERPRINTS: tuple[str, ...] = (
    # text / generic / happy_path — minimal signed-amount baseline
    "d69fbafcecb481e614651b1178a5fb9d9e3724718ef7bf623502120bcd27db30",
    # text / generic / duplicate_rows — the #1254 duplicate-deposit edge
    "cb5dd1f714784190dab3356c17d635a0e09b8f9fca78abb6023218ca29efcbab",
    # vision / brokerage (Futu) — real month with ZERO transactions
    "05d7858b5baa76e92d75f39b2c7d101d16aac776c608488affc21a14c1f754c1",
    # vision / bank (CMB) — largest real statement, balance chain ties
    "61dcbca67c96bb5371188772a290d30d868be8c2ed4533352b4c4bb8a44fc046",
    # vision / bank (MariBank) — second real bank, balance chain ties
    "25e00d6718d89f0fe44dc9acf4333649bbfa467780422ef2c6b9db322d96ea21",
    # vision / brokerage (Moomoo) — 48 txns, negative closing balance
    "a531a974fd0bd144fd4a31f63d94384210f043c94bfc81631b20d3f178c779ed",
    # vision / named_bank — synthetic OCR class distinct from generic_hf
    "d2bef919d2918989d2a6dbc8bbf019bd6bd2107d97f2e1bd85c91185c36e4fd0",
    # vision / generic_hf — largest corpus statement (170 txns)
    "5f1ef733e543f140966bfaadc1be1e2acc012ef4ca7394379228cd9896a5d934",
    # text / generic_hf — 161-txn large text statement
    "69e9b2c1b2fb563811851dbd3a33096b68ef8f39261a0951fa3b7a5dcf7d4484",
    # text / generic_hf — 163-txn large text statement, 8-figure closing
    "4ec965fd2615a4b285964aab735b385feae08fc754282629b39101ae12083efe",
)

ZERO_TXN_FINGERPRINT = "05d7858b5baa76e92d75f39b2c7d101d16aac776c608488affc21a14c1f754c1"

# Known-unpostable rows per cassette: frozen extraction outputs are committed
# verbatim, and two of them carry a row that cannot become a Layer-2
# AtomicTransaction (amount None / amount == 0, which the DB's
# ck_atomic_transactions_amount_positive rejects). The loader drops these
# LOUDLY: any drop not in this exact allowlist fails the manifest test, so a
# re-recorded cassette that silently loses pricing on more rows is caught.
KNOWN_UNPOSTABLE_ROWS: dict[str, int] = {
    # vision / generic_hf 170-txn statement: one amount == 0 row
    "5f1ef733e543f140966bfaadc1be1e2acc012ef4ca7394379228cd9896a5d934": 1,
    # text / generic_hf 161-txn statement: one amount == None row
    "69e9b2c1b2fb563811851dbd3a33096b68ef8f39261a0951fa3b7a5dcf7d4484": 1,
}


@dataclass(frozen=True)
class CorpusCase:
    """One corpus statement: the cassette's frozen extraction output + truth metadata."""

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
        total = Decimal("0")
        for row in self.rows:
            if row["direction"] == TransactionDirection.IN:
                total += row["amount"]
            else:
                total -= row["amount"]
        return total


def load_corpus_case(fingerprint: str) -> CorpusCase:
    """Build a seedable case from a cassette + its ground-truth metadata."""
    cassette = json.loads((CASSETTE_DIR / f"{fingerprint}.json").read_text())
    truth = json.loads((GROUND_TRUTH_DIR / f"{fingerprint}.truth.json").read_text())
    payload = json.loads(cassette["response"]["stream_text"])

    # Two frozen output schemas exist: vision cassettes emit unsigned amounts
    # with an explicit ``direction``; text cassettes emit signed amounts where
    # the sign IS the direction. Both normalise to (abs Decimal, direction).
    rows = []
    unpostable = 0
    for index, txn in enumerate(payload["transactions"]):
        if txn["amount"] is None or Decimal(str(txn["amount"])) == 0:
            # Raw extraction artifact: the frozen output can carry a row it
            # failed to price (None) or a zero-amount row — neither can become
            # a Layer-2 AtomicTransaction (ck_atomic_transactions_amount_positive).
            # Counted, not silent: the manifest test pins the exact per-case
            # count via KNOWN_UNPOSTABLE_ROWS.
            unpostable += 1
            continue
        amount = Decimal(str(txn["amount"]))
        if "direction" in txn:
            raw_direction = str(txn["direction"]).upper()
            if raw_direction not in ("IN", "OUT"):
                raise ValueError(f"{fingerprint[:8]}: unknown direction {txn['direction']!r} in cassette row {index}")
            direction = TransactionDirection.IN if raw_direction == "IN" else TransactionDirection.OUT
        else:
            direction = TransactionDirection.IN if amount >= 0 else TransactionDirection.OUT
        rows.append(
            {
                "description": txn["description"] or f"corpus txn {index}",
                # Monetary red line: Decimal, never float.
                "amount": abs(amount),
                "direction": direction,
                "date": date.fromisoformat(txn["date"]),
            }
        )
    rows = tuple(rows)
    return CorpusCase(
        fingerprint=fingerprint,
        modality=truth["modality"],
        institution_class=truth["institution_class"],
        edge_condition=truth["edge_condition"],
        institution=payload.get("institution") or truth["institution_class"].title(),
        opening_balance=Decimal(str(payload["opening_balance"])),
        rows=rows,
        unpostable_rows=unpostable,
    )


@pytest.mark.e2e
def test_corpus_manifest_is_diverse():
    """EPIC-023 / AC-llm.11.1: the corpus manifest's diversity invariants hold in code.

    GIVEN the committed 10-fingerprint corpus manifest
    WHEN loading each cassette + truth pair
    THEN the corpus spans both modalities, bank AND brokerage classes, the
    duplicate-rows edge, a zero-transaction statement, and >=3 statements of
    150+ transactions — so a future edit cannot silently homogenize the corpus.
    """
    assert len(CORPUS_FINGERPRINTS) == 10
    assert len(set(CORPUS_FINGERPRINTS)) == 10, "corpus fingerprints must be unique"

    cases = [load_corpus_case(fp) for fp in CORPUS_FINGERPRINTS]

    modalities = {case.modality for case in cases}
    assert modalities == {"text", "vision"}, f"corpus must span both modalities, got {modalities}"

    classes = {case.institution_class for case in cases}
    assert "bank" in classes and "brokerage" in classes, f"corpus must span bank+brokerage, got {classes}"

    edge_conditions = {case.edge_condition for case in cases}
    assert "duplicate_rows" in edge_conditions, "the #1254 duplicate-rows edge must stay in the corpus"

    txn_counts = sorted(len(case.rows) for case in cases)
    assert txn_counts[0] == 0, "the zero-transaction statement must stay in the corpus"
    assert sum(1 for n in txn_counts if n >= 150) >= 3, f"need >=3 large statements (150+ txns), got {txn_counts}"

    # Every case must be seedable: direction resolved for every row, Decimal amounts.
    for case in cases:
        for row in case.rows:
            assert isinstance(row["amount"], Decimal)
            assert row["direction"] in (TransactionDirection.IN, TransactionDirection.OUT)

    # Unpostable rows (amount None / zero in the frozen output) are dropped by
    # the loader but never silently: the per-case count must equal the exact
    # committed allowlist, so a re-recorded cassette losing pricing on more
    # rows — or an allowlist entry going stale — fails here.
    actual_unpostable = {case.fingerprint: case.unpostable_rows for case in cases if case.unpostable_rows}
    assert actual_unpostable == KNOWN_UNPOSTABLE_ROWS, (
        f"unpostable-row drift: expected {KNOWN_UNPOSTABLE_ROWS}, got {actual_unpostable}"
    )


@ac_proof(
    "extraction-corpus-journeys-pr",
    ac_ids=["AC-llm.11.2"],
    scope="behavioral",
    ci_tier="pr_ci",
    trust_mode="deterministic_pr",
    source_classes=["bank_statement"],
    issue="#1613",
)
@pytest.mark.e2e
@pytest.mark.parametrize("fingerprint", CORPUS_FINGERPRINTS, ids=lambda fp: fp[:8])
async def test_corpus_statement_full_journey(client, db, test_user, fingerprint):
    """EPIC-023 / AC-llm.11.2: every corpus extraction output completes the downstream journey.

    GIVEN a corpus cassette's frozen extraction output seeded as a parsed statement
    WHEN driving transactions → review → approve → reconciliation → balance sheet via the API
    THEN each stage reports the exact corpus-derived numbers with zero provider calls.
    """
    case = load_corpus_case(fingerprint)
    seeded = await seed_parsed_statement(
        db,
        test_user.id,
        institution=case.institution,
        original_filename=f"corpus_{case.short_id}.pdf",
        opening_balance=case.opening_balance,
        transactions=[dict(row) for row in case.rows],
    )
    stmt_id = str(seeded.id)
    n = len(case.rows)

    # Parsed surface: list row, transactions endpoint, exact count, Decimal-safe amounts.
    list_resp = await client.get("/statements")
    assert list_resp.status_code == 200, list_resp.text
    assert stmt_id in [item["id"] for item in list_resp.json()["items"]]

    txns_resp = await client.get(f"/statements/{stmt_id}/transactions")
    assert txns_resp.status_code == 200, txns_resp.text
    api_txns = txns_resp.json()["items"]
    assert len(api_txns) == n, f"[{case.short_id}] expected {n} transactions, got {len(api_txns)}"
    for item in api_txns:
        assert Decimal(str(item["amount"])) > 0
        assert item["direction"] in {"IN", "OUT"}

    # Stage-1 review: the seeded balance chain (open + ΣIN − ΣOUT = close) must validate.
    review_resp = await client.get(f"/statements/{stmt_id}/review")
    assert review_resp.status_code == 200, review_resp.text
    review = review_resp.json()
    assert len(review["transactions"]) == n
    validation = review["balance_validation_result"]
    assert validation["closing_match"] is True, f"[{case.short_id}] balance chain must tie: {validation}"

    # Real statements carry same-day duplicate / opposite-direction rows that
    # the Stage-1 guard flags for review (#962, the #1254 edge). Walk the same
    # path a reviewer would: inspect the candidates, confirm they are distinct.
    conflicts_resp = await client.get(f"/review/conflicts/{stmt_id}")
    assert conflicts_resp.status_code == 200, conflicts_resp.text
    conflicts = conflicts_resp.json()
    if conflicts["duplicates"] or conflicts["transfer_pairs"]:
        resolve_resp = await client.post(
            f"/review/conflicts/{stmt_id}/resolve",
            json={"action": "confirm_distinct", "note": f"corpus {case.short_id}: source rows verified"},
        )
        assert resolve_resp.status_code == 200, resolve_resp.text

    # Approve: one posted journal entry per corpus transaction. The corpus
    # institutions are fresh per test user, so ask Stage 1 to create the
    # posting account from the statement's own identity.
    approve_resp = await client.post(
        f"/statements/{stmt_id}/review/approve",
        json={"create_account_if_missing": True},
    )
    assert approve_resp.status_code == 200, approve_resp.text
    approved = approve_resp.json()
    assert approved["journal_entries_created"] == n
    account_id = approved["account_id"]
    assert account_id, f"[{case.short_id}] approve must resolve a posting account"

    # Reconciliation: a statement-scoped run must clear every corpus transaction.
    run_resp = await client.post("/reconciliation/runs", json={"statement_id": stmt_id})
    assert run_resp.status_code == 200, run_resp.text
    run = run_resp.json()
    assert run["unmatched"] == 0, f"[{case.short_id}] reconciliation left unmatched rows: {run}"

    # Report: the balance sheet reflects the statement's net movement on the
    # posting account, and the accounting equation holds.
    report_resp = await client.get("/reports/balance-sheet")
    assert report_resp.status_code == 200, report_resp.text
    report = report_resp.json()
    assert report["is_balanced"] is True, f"[{case.short_id}] accounting equation must balance"

    if n:
        lines = {line["account_id"]: Decimal(str(line["amount"])) for line in report["assets"]}
        assert account_id in lines, f"[{case.short_id}] posting account missing from balance sheet assets"
        assert lines[account_id] == case.net_movement, (
            f"[{case.short_id}] balance sheet shows {lines[account_id]}, corpus net movement is {case.net_movement}"
        )


@pytest.mark.e2e
async def test_corpus_zero_transaction_statement_approves_empty(client, db, test_user):
    """EPIC-023 / AC-llm.11.3: the zero-transaction corpus statement is deterministic end-to-end.

    GIVEN the real brokerage month with no activity, seeded from its cassette
    WHEN reviewing, approving, and reconciling it
    THEN review shows a trivially-tied chain over zero rows, approve reports
    journal_entries_created == 0, and the statement-scoped run has unmatched == 0.
    """
    case = load_corpus_case(ZERO_TXN_FINGERPRINT)
    assert not case.rows, "manifest drift: the zero-transaction fingerprint gained rows"

    seeded = await seed_parsed_statement(
        db,
        test_user.id,
        institution=case.institution,
        original_filename=f"corpus_{case.short_id}.pdf",
        opening_balance=case.opening_balance,
        transactions=[],
    )
    stmt_id = str(seeded.id)

    review_resp = await client.get(f"/statements/{stmt_id}/review")
    assert review_resp.status_code == 200, review_resp.text
    review = review_resp.json()
    assert review["transactions"] == []
    assert review["balance_validation_result"]["closing_match"] is True

    approve_resp = await client.post(
        f"/statements/{stmt_id}/review/approve",
        json={"create_account_if_missing": True},
    )
    assert approve_resp.status_code == 200, approve_resp.text
    assert approve_resp.json()["journal_entries_created"] == 0

    run_resp = await client.post("/reconciliation/runs", json={"statement_id": stmt_id})
    assert run_resp.status_code == 200, run_resp.text
    assert run_resp.json()["unmatched"] == 0

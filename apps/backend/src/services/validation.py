"""Validation helpers for statement extraction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from src.audit.money.adopt import balance_check
from src.models.statement_enums import BankStatementStatus

BALANCE_TOLERANCE = Decimal("0.10")
IN_DIRECTION_ALIASES = {"IN", "CREDIT", "CR", "DEPOSIT", "INFLOW"}
OUT_DIRECTION_ALIASES = {"OUT", "DEBIT", "DR", "WITHDRAWAL", "WITHDRAW", "OUTFLOW", "PAYMENT"}

# Under-extraction guard (issue #967). A brokerage statement that yields at most
# one transaction is a strong under-capture signal — comparable brokerage
# statements extract ~10 rows — so its confidence must not present as high.
BROKERAGE_MIN_PLAUSIBLE_TXNS = 2
UNDER_EXTRACTION_SCORE_CAP = 60


def normalize_amount_direction(amount: Decimal, direction_value: Any = None) -> tuple[Decimal, str]:
    """Return absolute amount plus canonical IN/OUT direction."""
    direction = str(direction_value or "").strip().upper()
    if direction in IN_DIRECTION_ALIASES:
        canonical_direction = "IN"
    elif direction in OUT_DIRECTION_ALIASES:
        canonical_direction = "OUT"
    else:
        canonical_direction = "OUT" if amount < 0 else "IN"
    return abs(amount), canonical_direction


def validate_balance(extracted: dict[str, Any]) -> dict[str, Any]:
    """Validate that opening + transactions ~= closing within tolerance.

    Dict-based entry point used by extraction; ``validate_balance_explicit``
    is the Decimal-based variant.
    """
    try:
        opening = Decimal(str(extracted.get("opening_balance") or "0"))
        closing = Decimal(str(extracted.get("closing_balance") or "0"))

        net = Decimal("0")
        for txn in extracted.get("transactions", []):
            amount = Decimal(str(txn["amount"]))
            amount, direction = normalize_amount_direction(amount, txn.get("direction"))
            if direction == "IN":
                net += amount
            else:
                net -= amount

        return validate_balance_explicit(opening, closing, net)
    except (ValueError, KeyError, InvalidOperation) as exc:
        # ``balance_computable=False`` flags that the difference could not be
        # derived (structurally-broken payload), so callers can branch on an
        # explicit flag instead of parsing the human-readable ``notes`` string.
        return {
            "balance_valid": False,
            "balance_computable": False,
            "expected_closing": "0",
            "actual_closing": "0",
            "difference": "0",
            "notes": f"Validation error: {exc}",
        }


def _currency_buckets(extracted: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve the per-currency opening/closing buckets for a statement.

    #1123 AC1. Prefers an explicit ``balances`` array
    (``[{currency, opening, closing}, ...]``). When absent — today's
    single-currency payloads — it falls back to the scalar
    ``opening_balance`` / ``closing_balance`` under the header ``currency`` (or a
    synthetic ``"*"`` bucket when no currency is stated), so the per-currency
    path degenerates to the existing scalar check without a cross-currency sum.
    """
    raw_balances = extracted.get("balances")
    if raw_balances:
        buckets: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in raw_balances:
            currency = (entry.get("currency") or "*").strip().upper() or "*"
            # Reject duplicate currencies rather than silently collapsing them.
            # ``nets`` is keyed by currency, so two buckets for the same code
            # would produce ambiguous, order-dependent results for that currency.
            # Failing loudly forces upstream parsing to merge the duplicate
            # opening/closing pair into a single authoritative bucket.
            if currency in seen:
                raise ValueError(f"Duplicate currency in balances: {currency}")
            seen.add(currency)
            buckets.append(
                {
                    "currency": currency,
                    "opening": Decimal(str(entry.get("opening") or "0")),
                    "closing": Decimal(str(entry.get("closing") or "0")),
                }
            )
        return buckets

    header_currency = (extracted.get("currency") or "*").strip().upper() or "*"
    return [
        {
            "currency": header_currency,
            "opening": Decimal(str(extracted.get("opening_balance") or "0")),
            "closing": Decimal(str(extracted.get("closing_balance") or "0")),
        }
    ]


def validate_balance_per_currency(extracted: dict[str, Any]) -> dict[str, Any]:
    """Validate ``open + ΣIN − ΣOUT ≈ close`` independently for each currency.

    #1123 AC1. Transactions are grouped by their own ``currency`` and each
    currency's running balance is checked against that currency's opening/closing
    pair. Currencies are NEVER summed together — a multi-currency statement is a
    set of independent single-currency closed loops. The legacy scalar check
    (:func:`validate_balance`) is the degenerate one-currency case of this rule.

    Returns a dict with an overall ``balance_valid`` (AND across currencies) plus
    a ``per_currency`` list, one :func:`validate_balance_explicit`-shaped result
    per currency tagged with its ``currency`` code. No cross-currency aggregate
    ``expected_closing`` is produced.

    A transaction whose currency has no declared balance bucket is NOT dropped:
    an orphan bucket (zero declared opening/closing, the computed net, flagged
    ``declared_balance=False``) is surfaced so no transaction currency goes
    silently unaccounted in a multi-currency statement.

    .. note::
       Wired into the brokerage extraction-write path (#1160): a failing
       per-currency self-check now marks the persisted statement
       ``balance_validated=False`` with a ``validation_error`` rather than being
       silently logged. The scalar :func:`validate_balance` still gates bank
       running-balance chains; the two are complementary, not competing.
    """
    try:
        buckets = _currency_buckets(extracted)

        # Net IN/OUT per currency. A transaction without an explicit currency
        # falls back to the single bucket when there is exactly one (the
        # degenerate case); with multiple buckets an untagged txn lands in "*".
        single_bucket_ccy = buckets[0]["currency"] if len(buckets) == 1 else None
        nets: dict[str, Decimal] = {b["currency"]: Decimal("0") for b in buckets}
        for txn in extracted.get("transactions", []):
            amount = Decimal(str(txn["amount"]))
            amount, direction = normalize_amount_direction(amount, txn.get("direction"))
            ccy = (txn.get("currency") or single_bucket_ccy or "*").strip().upper() or "*"
            nets.setdefault(ccy, Decimal("0"))
            nets[ccy] += amount if direction == "IN" else -amount
    except (ValueError, KeyError, InvalidOperation) as exc:
        return {
            "balance_valid": False,
            "balance_computable": False,
            "per_currency": [],
            "notes": f"Validation error: {exc}",
        }

    declared = {bucket["currency"] for bucket in buckets}
    per_currency: list[dict[str, Any]] = []
    for bucket in buckets:
        ccy = bucket["currency"]
        result = validate_balance_explicit(
            bucket["opening"], bucket["closing"], nets.get(ccy, Decimal("0")), currency=ccy
        )
        result["currency"] = ccy
        result["declared_balance"] = True
        per_currency.append(result)

    # Surface orphan currencies — those that appear in transactions but have no
    # declared balance bucket. Without this, such transactions are dropped and a
    # multi-currency statement could appear to reconcile while real money in an
    # undeclared currency goes unaccounted. Each orphan is reported against a
    # zero opening/closing so its non-zero net forces the bucket invalid.
    for ccy in nets:
        if ccy in declared:
            continue
        result = validate_balance_explicit(Decimal("0"), Decimal("0"), nets[ccy], currency=ccy)
        result["currency"] = ccy
        result["declared_balance"] = False
        if result["notes"] is None:
            result["notes"] = f"No declared balance for currency {ccy}"
        per_currency.append(result)

    return {
        "balance_valid": all(r["balance_valid"] for r in per_currency),
        "balance_computable": True,
        "per_currency": per_currency,
    }


def bank_currency_balances(extracted: dict[str, Any]) -> list[dict[str, str]] | None:
    """Per-currency opening/closing for a *bank* statement, mirroring the brokerage
    array (#1139) — but only when the statement is genuinely multi-currency.

    A multi-currency bank statement (e.g. a DBS consolidated / multi-currency
    account) must not collapse its currencies into one scalar opening/closing —
    cross-summing unrelated currencies yields a meaningless balance. When the
    payload declares a per-currency ``balances`` array spanning >1 currency, this
    returns the ``[{currency, opening, closing}]`` shape (string amounts,
    JSONB-ready) consumed by :func:`validate_balance_per_currency` and persisted on
    ``StatementSummary.currency_balances``. A single-currency statement returns
    ``None`` so the existing scalar path is unchanged (backward compatible).
    """
    if not extracted.get("balances"):
        return None
    buckets = _currency_buckets(extracted)
    if len({bucket["currency"] for bucket in buckets}) < 2:
        return None
    return [
        {
            "currency": bucket["currency"],
            "opening": str(bucket["opening"]),
            "closing": str(bucket["closing"]),
        }
        for bucket in buckets
    ]


def validate_balance_explicit(
    opening: Decimal,
    closing: Decimal,
    net_transactions: Decimal,
    currency: str | None = None,
) -> dict[str, Any]:
    """Validate balance using explicit Decimal values.

    When ``currency`` is a valid ISO-4217 code the per-currency arithmetic is
    routed through same-currency :class:`Money` (#1171 AC2.22.2) so a multi-currency
    statement cannot cross-sum; the ``"*"`` sentinel / non-ISO codes use the
    identical Decimal arithmetic. Byte-identical either way.
    """
    expected_closing, diff = balance_check(opening, closing, net_transactions, currency)
    balance_valid = diff <= BALANCE_TOLERANCE

    return {
        "balance_valid": balance_valid,
        "balance_computable": True,
        "expected_closing": str(expected_closing),
        "actual_closing": str(closing),
        "difference": f"{diff:.2f}",
        "notes": None if balance_valid else f"Balance mismatch: expected {expected_closing}, got {closing}",
    }


@dataclass(frozen=True)
class ChainBreak:
    """A pinpointed break in a statement's running-balance chain (AC13.20 / #1140).

    The running balance (``balance_after``) of transaction ``index`` does not equal
    the previous running balance plus ``index``'s own signed amount (within
    ``BALANCE_TOLERANCE``). That is the deterministic fingerprint of a row that was
    *missed or misparsed* between the previous row and this one — the most common
    shape of bank-statement under-extraction.

    All amounts are ``Decimal`` (never ``float``): ``index`` is the 0-based
    position of the first non-reconciling row, ``expected_balance`` is what the
    chain predicted, ``observed_balance`` is what the parse reported, and ``delta``
    is ``observed - expected`` (signed, so a positive delta means the observed
    balance is higher than the chain predicted — i.e. an ``OUT`` row was likely
    dropped, and vice-versa).
    """

    index: int
    expected_balance: Decimal
    observed_balance: Decimal

    @property
    def delta(self) -> Decimal:
        return self.observed_balance - self.expected_balance


def detect_balance_chain_break(
    transactions: list[dict[str, Any]],
    *,
    opening_balance: Decimal | None = None,
    tolerance: Decimal = BALANCE_TOLERANCE,
) -> ChainBreak | None:
    """Locate the first running-balance discontinuity in an ordered txn list (AC-C1).

    Walks the ordered transactions and checks, for each row that carries a
    ``balance_after``, that ``previous_balance + signed_amount == balance_after``
    within ``tolerance``. The "previous balance" is the prior row's
    ``balance_after`` (or ``opening_balance`` for the first row, when supplied).
    Returns the first :class:`ChainBreak` found, or ``None`` if the chain is
    consistent / too short to check.

    Fully deterministic and ``Decimal``-based — it never calls a model and never
    uses ``float`` — so it is safe to run on every parse to pinpoint where a row
    was dropped or misparsed. Rows whose ``balance_after``/``amount`` cannot be
    coerced to ``Decimal`` are skipped (they carry no chain signal); the previous
    balance simply does not advance across an unparseable row.
    """
    prev_balance: Decimal | None = opening_balance

    for index, txn in enumerate(transactions):
        raw_balance = txn.get("balance_after")
        raw_amount = txn.get("amount")
        if raw_balance is None or raw_amount is None:
            # No running-balance signal on this row; cannot extend the chain.
            continue
        try:
            observed = Decimal(str(raw_balance))
            amount = Decimal(str(raw_amount))
        except (ValueError, TypeError, InvalidOperation):
            continue

        amount, direction = normalize_amount_direction(amount, txn.get("direction"))
        signed = amount if direction == "IN" else -amount

        if prev_balance is not None:
            expected = prev_balance + signed
            if abs(observed - expected) > tolerance:
                return ChainBreak(index=index, expected_balance=expected, observed_balance=observed)

        prev_balance = observed

    return None


def count_within_document_dedup_collapse(dedup_hashes: list[str]) -> int:
    """Count transactions lost to within-a-single-parse dedup collapse (#1254 shape).

    Given the ordered ``dedup_hash`` values produced for the rows of **one**
    document parse, return ``len(hashes) - len(distinct hashes)`` — how many rows
    were silently absorbed because they hashed identically to an earlier row in
    the *same* parse.

    This is a pure within-document conservation check. It is deliberately scoped
    to a single document's freshly-built rows and is computed BEFORE any database
    upsert, so legitimate CROSS-document dedup (the same transaction re-uploaded in
    a later statement, which collapses against an already-persisted row) can never
    trigger it — that collapse happens later, against the DB, and is never counted
    here. A non-zero result means two rows *within this one parse* that the
    per-document ``occurrence_index`` disambiguator (see
    :meth:`DeduplicationService.calculate_transaction_hash`) was expected to keep
    distinct still collided — exactly the #1254 class of silent row loss. The
    detector is conservative: it never over-reports, because the count is purely
    the number of extra (duplicate) hashes within this single parse.
    """
    if not dedup_hashes:
        return 0
    return len(dedup_hashes) - len(set(dedup_hashes))


def validate_completeness(extracted: dict[str, Any]) -> list[str]:
    """Return missing required fields for a statement."""
    required_fields = [
        "institution",
        "period_start",
        "period_end",
        "opening_balance",
        "closing_balance",
    ]
    return [field for field in required_fields if not extracted.get(field)]


def compute_confidence_score(
    extracted: dict[str, Any],
    balance_result: dict[str, Any],
    missing_fields: list[str] | None = None,
    *,
    is_brokerage: bool = False,
    effective_txn_count: int | None = None,
) -> int:
    """Compute confidence score (0-100) based on SSOT V2 weights.

    Weights: Balance 35% | Completeness 25% | Format 15% | Txn Count 10%
           | Balance Progression 10% | Currency Consistency 5%

    The Balance Progression component (10%) is only awarded when transactions
    carry a per-line running ``balance_after`` chain. Statements without that
    chain therefore top out near 90 even when otherwise clean — this is the
    documented ceiling, not a bug (issue #967).

    When ``is_brokerage`` is set and the parse yields an implausibly low
    transaction count (``< BROKERAGE_MIN_PLAUSIBLE_TXNS``), the score is capped
    at ``UNDER_EXTRACTION_SCORE_CAP`` so under-capture does not present as high
    confidence. The under-extraction check uses ``effective_txn_count`` when
    provided — the count of *persisted* transactions after skipped/invalid rows
    — falling back to the raw extracted-payload count otherwise.
    """
    if missing_fields is None:
        missing_fields = validate_completeness(extracted)

    score = 0
    transactions = extracted.get("transactions", []) or []

    # Balance validation (35%)
    if balance_result.get("balance_proof_available", True):
        if balance_result["balance_valid"]:
            score += 35
        else:
            try:
                diff = Decimal(str(balance_result.get("difference", "0") or "0"))
                if diff <= Decimal("1.00"):
                    score += 25
                elif diff <= Decimal("10.00"):
                    score += 17
            except (ValueError, TypeError, InvalidOperation):
                pass

    # Field completeness (25%)
    required_fields_count = 5
    present = required_fields_count - len(missing_fields)
    score += int((present / required_fields_count) * 25)

    # Format consistency (15%)
    format_score = 15
    try:
        if extracted.get("period_start"):
            date.fromisoformat(str(extracted["period_start"]))
        if extracted.get("period_end"):
            date.fromisoformat(str(extracted["period_end"]))
        Decimal(str(extracted.get("opening_balance", "0") or "0"))
        Decimal(str(extracted.get("closing_balance", "0") or "0"))
    except (ValueError, TypeError, InvalidOperation):
        format_score = 0
    score += format_score

    # Transaction count (10%)
    txn_count = len(transactions)
    if 1 <= txn_count <= 500:
        score += 10
    elif txn_count > 500:
        score += 5

    # Balance progression (10%)
    score += _score_balance_progression(transactions)

    # Currency consistency (5%)
    header_currency = extracted.get("currency")
    score += _score_currency_consistency(transactions, header_currency)

    score = min(100, score)

    # Under-extraction penalty (issue #967): a brokerage statement with an
    # implausibly low transaction count is likely an under-capture, so cap the
    # score below the auto-approve band regardless of how clean the captured
    # rows look. Prefer the persisted count (after skipped/invalid rows) so a
    # payload that extracts 2 rows but persists only 1 still trips the cap.
    txn_count = effective_txn_count if effective_txn_count is not None else len(transactions)
    if is_brokerage and txn_count < BROKERAGE_MIN_PLAUSIBLE_TXNS:
        score = min(score, UNDER_EXTRACTION_SCORE_CAP)

    return score


def _score_balance_progression(transactions: list[dict[str, Any]]) -> int:
    """Score 0-10 based on balance_after chain consistency.

    Checks: balance_after[n] == balance_after[n-1] +/- amount[n] within tolerance.
    """
    balances = []
    for txn in transactions:
        bal = txn.get("balance_after")
        amt = txn.get("amount")
        direction = str(txn.get("direction", "IN")).upper()
        if bal is not None and amt is not None:
            try:
                amount = Decimal(str(amt))
                amount, direction = normalize_amount_direction(amount, direction)
                balances.append((Decimal(str(bal)), amount, direction))
            except (ValueError, TypeError, InvalidOperation):
                continue

    if len(balances) < 2:
        return 0

    consistent = 0
    total = len(balances) - 1
    tolerance = Decimal("0.10")
    for i in range(1, len(balances)):
        prev_bal = balances[i - 1][0]
        cur_bal, cur_amt, cur_dir = balances[i]
        if cur_dir == "IN":
            expected = prev_bal + cur_amt
        else:
            expected = prev_bal - cur_amt
        if abs(cur_bal - expected) <= tolerance:
            consistent += 1

    if total == 0:
        return 0
    ratio = consistent / total
    return int(ratio * 10)


def _score_currency_consistency(transactions: list[dict[str, Any]], header_currency: str | None) -> int:
    """Score 0-5 based on per-transaction currency matching header currency."""
    if not transactions:
        return 0

    all_currencies = [txn.get("currency") for txn in transactions]
    non_empty_currencies = [c for c in all_currencies if c]

    if not non_empty_currencies:
        return 0

    if not header_currency:
        from collections import Counter

        most_common = Counter(non_empty_currencies).most_common(1)[0][0]
        header_currency = most_common

    matching = sum(1 for c in all_currencies if c == header_currency)
    ratio = matching / len(transactions)
    return int(ratio * 5)


def route_by_threshold(score: int, balance_valid: bool) -> BankStatementStatus:
    """Route a parsed bank statement by confidence threshold and balance validity.

    Resting states (#1141):

    - **Balance invalid** -> ``PARSED`` (review) regardless of score. The statement
      parsed but its running balance does not reconcile; it must enter review
      carrying a ``validation_error`` — the same reviewable resting state as a
      brokerage statement. It is never parked in ``uploaded``, which was a
      dead-end the retry endpoint rejected and report readiness ignored (#1085).
      It also never auto-approves: an unreconciled balance must be human-reviewed.
    - **Balance valid, score >= 85** -> ``APPROVED`` (auto-accept).
    - **Balance valid, score >= 60** -> ``PARSED`` (review).
    - **Balance valid, score < 60** -> ``UPLOADED``: a genuinely low-signal parse
      where there is not enough extracted structure to review meaningfully, so the
      user is routed to manual entry. (Distinct from the balance-invalid case,
      where there *is* a reviewable parse that merely fails reconciliation.)
    """
    if not balance_valid:
        return BankStatementStatus.PARSED
    if score >= 85:
        return BankStatementStatus.APPROVED
    if score >= 60:
        return BankStatementStatus.PARSED
    return BankStatementStatus.UPLOADED

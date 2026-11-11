"""Validation helpers for statement extraction."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from src.audit.money.adopt import balance_check
from src.extraction.base.source_vocabulary import BankStatementStatus

HIGH_CONFIDENCE_AUTO_APPROVE_THRESHOLD = 85
BALANCE_TOLERANCE = Decimal("0.10")
IN_DIRECTION_ALIASES = {"IN", "CREDIT", "CR", "DEPOSIT", "INFLOW"}
OUT_DIRECTION_ALIASES = {"OUT", "DEBIT", "DR", "WITHDRAWAL", "WITHDRAW", "OUTFLOW", "PAYMENT"}
STATEMENT_RESOLVED_TRANSACTIONS_ATTR = "_resolved_transactions"
BROKERAGE_MIN_PLAUSIBLE_TXNS = 2
UNDER_EXTRACTION_SCORE_CAP = 60


def normalize_amount_direction(amount: Decimal, direction_value: Any = None) -> tuple[Decimal, str]:
    """Return absolute amount plus canonical IN/OUT direction."""
    direction = str(direction_value or "").strip().upper()
    if direction in IN_DIRECTION_ALIASES:
        return abs(amount), "IN"
    if direction in OUT_DIRECTION_ALIASES:
        return abs(amount), "OUT"
    return abs(amount), ("OUT" if amount < 0 else "IN")


def should_invert_positive_balance_owed(
    opening: Decimal,
    closing: Decimal,
    net: Decimal,
    txn_count: int,
    *,
    tolerance: Decimal = BALANCE_TOLERANCE,
) -> bool:
    """Return True when credit-card positive balance-owed sign inversion reconciles the chain."""
    return (
        txn_count >= 2
        and net != Decimal("0")
        and abs((opening + net) - closing) > tolerance
        and abs((opening - net) - closing) <= Decimal("0.01")
    )


def _safe_parse_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except (ValueError, TypeError, InvalidOperation):
        return None


def _derive_running_balance_endpoints(
    transactions: list[dict[str, Any]],
    *,
    opening_balance: Decimal | None = None,
    closing_balance: Decimal | None = None,
    currency: str | None = None,
) -> tuple[Decimal, Decimal] | None:
    if not transactions:
        return None
    parsed_chain: list[tuple[Decimal, Decimal]] = []
    net = Decimal("0")
    for txn in transactions:
        amt = _safe_parse_decimal(txn.get("amount"))
        bal = _safe_parse_decimal(txn.get("balance_after"))
        if amt is None or bal is None:
            return None
        amt, direction = normalize_amount_direction(amt, txn.get("direction"))
        signed = amt if direction == "IN" else -amt
        net += signed
        parsed_chain.append((signed, bal))

    first_signed, first_balance_after = parsed_chain[0]
    resolved_opening = opening_balance if opening_balance is not None else (first_balance_after - first_signed)
    resolved_closing = closing_balance if closing_balance is not None else parsed_chain[-1][1]
    if detect_balance_chain_break(transactions, opening_balance=resolved_opening) is not None:
        return None
    if not validate_balance_explicit(resolved_opening, resolved_closing, net, currency=currency)["balance_valid"]:
        return None
    return resolved_opening, resolved_closing


def normalize_statement_balance_payload(extracted: dict[str, Any]) -> dict[str, Any]:
    """Deterministically normalize multi-currency, running-balance, and credit-card balance payloads."""
    if not isinstance(extracted, dict):
        return extracted

    raw_txns = extracted.get("transactions")
    transactions = [txn for txn in raw_txns if isinstance(txn, dict)] if isinstance(raw_txns, list) else []
    header_ccy = str(extracted.get("currency") or "").strip().upper() or None
    txn_groups: dict[str, list[dict[str, Any]]] = {}
    for txn in transactions:
        ccy = str(txn.get("currency") or header_ccy or "").strip().upper()
        if ccy:
            txn_groups.setdefault(ccy, []).append(txn)

    raw_balances = extracted.get("balances")
    if not raw_balances and len(txn_groups) >= 2:
        synthesized: list[dict[str, str]] = []
        for ccy, group_txns in txn_groups.items():
            endpoints = _derive_running_balance_endpoints(group_txns, currency=ccy)
            if endpoints is None:
                break
            synthesized.append({"currency": ccy, "opening": str(endpoints[0]), "closing": str(endpoints[1])})
        if len(synthesized) == len(txn_groups):
            extracted["balances"] = raw_balances = synthesized

    if isinstance(raw_balances, list) and raw_balances:
        primary_bucket = next(
            (
                b
                for b in raw_balances
                if isinstance(b, dict) and str(b.get("currency") or "").strip().upper() == (header_ccy or "")
            ),
            raw_balances[0] if isinstance(raw_balances[0], dict) else None,
        )
        if isinstance(primary_bucket, dict):
            if extracted.get("currency") is None and primary_bucket.get("currency"):
                extracted["currency"] = str(primary_bucket["currency"]).strip().upper()
            if extracted.get("opening_balance") is None and primary_bucket.get("opening") is not None:
                extracted["opening_balance"] = str(primary_bucket["opening"])
            if extracted.get("closing_balance") is None and primary_bucket.get("closing") is not None:
                extracted["closing_balance"] = str(primary_bucket["closing"])

    opening_dec = _safe_parse_decimal(extracted.get("opening_balance"))
    closing_dec = _safe_parse_decimal(extracted.get("closing_balance"))
    if not extracted.get("balances") and len(txn_groups) <= 1 and (opening_dec is None or closing_dec is None):
        single_ccy = header_ccy or (next(iter(txn_groups)) if txn_groups else None)
        endpoints = _derive_running_balance_endpoints(
            transactions, opening_balance=opening_dec, closing_balance=closing_dec, currency=single_ccy
        )
        if endpoints is not None:
            opening_dec, closing_dec = endpoints
            if extracted.get("opening_balance") is None:
                extracted["opening_balance"] = str(opening_dec)
            if extracted.get("closing_balance") is None:
                extracted["closing_balance"] = str(closing_dec)
            if extracted.get("currency") is None and single_ccy:
                extracted["currency"] = single_ccy

    if not extracted.get("balances") and opening_dec is not None and closing_dec is not None and len(transactions) >= 2:
        parsed_amts = [(_safe_parse_decimal(txn.get("amount")), txn.get("direction")) for txn in transactions]
        if all(amt is not None for amt, _ in parsed_amts):
            net = sum(
                (
                    amt if direction == "IN" else -amt
                    for raw_amt, raw_dir in parsed_amts
                    if raw_amt is not None
                    for amt, direction in (normalize_amount_direction(raw_amt, raw_dir),)
                ),
                Decimal("0"),
            )
            if should_invert_positive_balance_owed(opening_dec, closing_dec, net, len(transactions)):
                extracted["opening_balance"] = str(-opening_dec)
                extracted["closing_balance"] = str(-closing_dec)
                for txn in transactions:
                    bal = _safe_parse_decimal(txn.get("balance_after"))
                    if bal is not None and bal > Decimal("0"):
                        txn["balance_after"] = str(-bal)

    return extracted


def validate_balance(extracted: dict[str, Any]) -> dict[str, Any]:
    """Validate that opening + transactions ~= closing within tolerance."""
    try:
        normalized = normalize_statement_balance_payload(extracted)
        opening = Decimal(str(normalized.get("opening_balance") or "0"))
        closing = Decimal(str(normalized.get("closing_balance") or "0"))
        net = Decimal("0")
        for txn in normalized.get("transactions", []):
            amount, direction = normalize_amount_direction(Decimal(str(txn["amount"])), txn.get("direction"))
            net += amount if direction == "IN" else -amount
        return validate_balance_explicit(opening, closing, net)
    except (ValueError, KeyError, InvalidOperation) as exc:
        return {
            "balance_valid": False,
            "balance_computable": False,
            "expected_closing": "0",
            "actual_closing": "0",
            "difference": "0",
            "notes": f"Validation error: {exc}",
        }


def _currency_buckets(extracted: dict[str, Any]) -> list[dict[str, Any]]:
    raw_balances = extracted.get("balances")
    if raw_balances:
        buckets: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in raw_balances:
            currency = (entry.get("currency") or "*").strip().upper() or "*"
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
    """Validate opening + IN - OUT == closing independently per currency."""
    try:
        buckets = _currency_buckets(extracted)
        single_bucket_ccy = buckets[0]["currency"] if len(buckets) == 1 else None
        nets: dict[str, Decimal] = {b["currency"]: Decimal("0") for b in buckets}
        for txn in extracted.get("transactions", []):
            amount, direction = normalize_amount_direction(Decimal(str(txn["amount"])), txn.get("direction"))
            ccy = (txn.get("currency") or single_bucket_ccy or "*").strip().upper() or "*"
            nets[ccy] = nets.get(ccy, Decimal("0")) + (amount if direction == "IN" else -amount)
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

    for ccy, net in nets.items():
        if ccy in declared:
            continue
        result = validate_balance_explicit(Decimal("0"), Decimal("0"), net, currency=ccy)
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
    """Return per-currency bank balances when spanning >= 2 currencies, else None."""
    normalized = normalize_statement_balance_payload(extracted) if not extracted.get("balances") else extracted
    if not normalized.get("balances"):
        return None
    buckets = _currency_buckets(normalized)
    if len({bucket["currency"] for bucket in buckets}) < 2:
        return None
    return [
        {"currency": bucket["currency"], "opening": str(bucket["opening"]), "closing": str(bucket["closing"])}
        for bucket in buckets
    ]


def balance_is_evaluable(opening: Any, closing: Any, per_currency: list[dict[str, str]] | None) -> bool:
    """Return True when the statement prints the balances that a reconcile check needs.

    A statement is evaluable with a per-currency balance list, or with both a scalar opening
    and a scalar closing balance. A missing balance cannot reconcile in any later pass.
    """
    if per_currency:
        return True
    return opening not in (None, "") and closing not in (None, "")


def validate_balance_explicit(
    opening: Decimal,
    closing: Decimal,
    net_transactions: Decimal,
    currency: str | None = None,
) -> dict[str, Any]:
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
    """First running-balance discontinuity in an ordered transaction list."""

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
    prev_balance: Decimal | None = opening_balance
    for index, txn in enumerate(transactions):
        raw_balance = txn.get("balance_after")
        raw_amount = txn.get("amount")
        if raw_balance is None or raw_amount is None:
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
    return len(dedup_hashes) - len(set(dedup_hashes)) if dedup_hashes else 0


def validate_completeness(extracted: dict[str, Any]) -> list[str]:
    required_fields = ("institution", "period_start", "period_end", "opening_balance", "closing_balance")
    return [field for field in required_fields if not extracted.get(field)]


def compute_confidence_score(
    extracted: dict[str, Any],
    balance_result: dict[str, Any],
    missing_fields: list[str] | None = None,
    *,
    is_brokerage: bool = False,
    effective_txn_count: int | None = None,
) -> int:
    """Compute confidence score (0-100) using SSOT V2 weights."""
    if missing_fields is None:
        missing_fields = validate_completeness(extracted)

    score = 0
    transactions = extracted.get("transactions", []) or []

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

    score += int(((5 - len(missing_fields)) / 5) * 25)

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

    txn_count = len(transactions)
    if 1 <= txn_count <= 500:
        score += 10
    elif txn_count > 500:
        score += 5

    score += _score_balance_progression(transactions)
    score += _score_currency_consistency(transactions, extracted.get("currency"))
    score = min(100, score)

    persisted_count = effective_txn_count if effective_txn_count is not None else txn_count
    if is_brokerage and persisted_count < BROKERAGE_MIN_PLAUSIBLE_TXNS:
        score = min(score, UNDER_EXTRACTION_SCORE_CAP)
    return score


def _score_balance_progression(transactions: list[dict[str, Any]]) -> int:
    balances = []
    for txn in transactions:
        bal, amt = txn.get("balance_after"), txn.get("amount")
        if bal is not None and amt is not None:
            try:
                amount, direction = normalize_amount_direction(Decimal(str(amt)), str(txn.get("direction", "IN")).upper())
                balances.append((Decimal(str(bal)), amount, direction))
            except (ValueError, TypeError, InvalidOperation):
                continue

    if len(balances) < 2:
        return 0
    consistent = sum(
        1
        for i in range(1, len(balances))
        if abs(balances[i][0] - (balances[i - 1][0] + (balances[i][1] if balances[i][2] == "IN" else -balances[i][1])))
        <= BALANCE_TOLERANCE
    )
    return int((consistent / (len(balances) - 1)) * 10)


def _score_currency_consistency(transactions: list[dict[str, Any]], header_currency: str | None) -> int:
    if not transactions:
        return 0
    all_currencies = [txn.get("currency") for txn in transactions]
    non_empty = [c for c in all_currencies if c]
    if not non_empty:
        return 0
    target = header_currency or Counter(non_empty).most_common(1)[0][0]
    return int((sum(1 for c in all_currencies if c == target) / len(transactions)) * 5)


def route_by_threshold(score: int, balance_valid: bool) -> BankStatementStatus:
    if not balance_valid:
        return BankStatementStatus.PARSED
    if score >= HIGH_CONFIDENCE_AUTO_APPROVE_THRESHOLD:
        return BankStatementStatus.APPROVED
    if score >= 60:
        return BankStatementStatus.PARSED
    return BankStatementStatus.UPLOADED

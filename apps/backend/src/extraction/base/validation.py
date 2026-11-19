"""Validation helpers for statement extraction."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from src.audit.money.adopt import balance_check
from src.extraction.base.normalization_engine import sanitize_account_last4

HIGH_CONFIDENCE_AUTO_APPROVE_THRESHOLD = 85
BALANCE_TOLERANCE = Decimal("0.10")
IN_DIRECTION_ALIASES = {"IN", "CREDIT", "CR", "DEPOSIT", "INFLOW"}
OUT_DIRECTION_ALIASES = {"OUT", "DEBIT", "DR", "WITHDRAWAL", "WITHDRAW", "OUTFLOW", "PAYMENT"}
BROKERAGE_MIN_PLAUSIBLE_TXNS = 2
UNDER_EXTRACTION_SCORE_CAP = 60
UNVERIFIED_SOURCE_SCORE_CAP = 80
MISSING_BALANCE_SCORE_CAP = 59

# Independent channel reliabilities (p_k = 1 - channel error probability) combined as 1 - prod(1 - p_k).
CHANNEL_RELIABILITY_BALANCE_EQUATION = Decimal("0.75")
CHANNEL_RELIABILITY_SOURCE_PROOF = Decimal("0.85")
CHANNEL_RELIABILITY_SPLIT_META = Decimal("0.45")
CHANNEL_RELIABILITY_PROGRESSION = Decimal("0.35")
CHANNEL_RELIABILITY_STRUCTURE = Decimal("0.40")


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


def repair_directions_from_running_balance(
    transactions: list[dict[str, Any]], *, opening_balance: Decimal | None = None
) -> int:
    """Set each direction that the printed running balance contradicts. Return the number of rows changed.

    A row is proven when the step from the previous balance equals its amount. The repair runs only when fewer
    than half of the proven rows disagree: a card that prints balances owed disagrees on every row, and the
    sign inversion handles it.
    """
    previous = opening_balance
    proven: list[tuple[dict[str, Any], Decimal, str, str]] = []
    for txn in transactions:
        balance = _safe_parse_decimal(txn.get("balance_after"))
        raw_amount = _safe_parse_decimal(txn.get("amount"))
        if balance is None:
            previous = None
            continue
        if raw_amount is not None and previous is not None:
            amount, stated = normalize_amount_direction(raw_amount, txn.get("direction"))
            step = balance - previous
            if step != 0 and abs(abs(step) - amount) <= BALANCE_TOLERANCE:
                proven.append((txn, amount, stated, "IN" if step > 0 else "OUT"))
        previous = balance
    wrong = [row for row in proven if row[2] != row[3]]
    if not wrong or len(wrong) * 2 >= len(proven):
        return 0
    for txn, amount, _stated, direction in wrong:
        txn["amount"] = str(amount)
        txn["direction"] = direction
    return len(wrong)


@dataclass(frozen=True, slots=True)
class BalanceNormalizationResult:
    """Normalized statement payload paired with printed source balance facts."""

    payload: dict[str, Any]
    printed_opening_balance: Decimal | None
    printed_closing_balance: Decimal | None
    printed_balances: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class AccountExtractionSlice:
    """One normalized per-account payload produced by multi-account splitting."""

    payload: dict[str, Any]
    sub_account_key: str
    analysis: BalanceNormalizationResult


def analyze_statement_balance_payload(extracted: dict[str, Any]) -> BalanceNormalizationResult:
    """Normalize printed balances & middle-row directions without writing derived endpoints back as printed facts."""
    if not isinstance(extracted, dict):
        return BalanceNormalizationResult(
            payload=extracted,
            printed_opening_balance=None,
            printed_closing_balance=None,
            printed_balances=(),
        )

    raw_txns = extracted.get("transactions")
    transactions = [txn for txn in raw_txns if isinstance(txn, dict)] if isinstance(raw_txns, list) else []
    header_ccy = str(extracted.get("currency") or "").strip().upper() or None
    txn_groups: dict[str, list[dict[str, Any]]] = {}
    for txn in transactions:
        ccy = str(txn.get("currency") or header_ccy or "").strip().upper()
        if ccy:
            txn_groups.setdefault(ccy, []).append(txn)

    raw_balances = extracted.get("balances")
    printed_balances_list: list[dict[str, str]] = []
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
        for b in raw_balances:
            if (
                isinstance(b, dict)
                and b.get("currency")
                and b.get("opening") is not None
                and b.get("closing") is not None
            ):
                printed_balances_list.append(
                    {
                        "currency": str(b["currency"]).strip().upper(),
                        "opening": str(b["opening"]),
                        "closing": str(b["closing"]),
                    }
                )
        if len(raw_balances) == 1 and len(txn_groups) <= 1:
            # A one-entry list repeats the scalar fields; keeping it would skip the card sign inversion below.
            del extracted["balances"]

    opening_dec = _safe_parse_decimal(extracted.get("opening_balance"))
    closing_dec = _safe_parse_decimal(extracted.get("closing_balance"))
    single_currency = len(txn_groups) <= 1
    for group in [transactions] if single_currency else txn_groups.values():
        repair_directions_from_running_balance(group, opening_balance=opening_dec if single_currency else None)

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
                opening_dec = -opening_dec
                closing_dec = -closing_dec
                extracted["opening_balance"] = str(opening_dec)
                extracted["closing_balance"] = str(closing_dec)
                for txn in transactions:
                    bal = _safe_parse_decimal(txn.get("balance_after"))
                    if bal is not None and bal > Decimal("0"):
                        txn["balance_after"] = str(-bal)

    return BalanceNormalizationResult(
        payload=extracted,
        printed_opening_balance=opening_dec,
        printed_closing_balance=closing_dec,
        printed_balances=tuple(printed_balances_list),
    )


class DuplicateCurrencyError(ValueError):
    """The balances of one statement list the same currency twice (usually two accounts in one PDF)."""

    def __init__(self, currency: str) -> None:
        super().__init__(f"Duplicate currency in balances: {currency}")
        self.currency = currency


def _currency_buckets(extracted: dict[str, Any]) -> list[dict[str, Any]]:
    raw_balances = extracted.get("balances")
    if raw_balances:
        buckets: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in raw_balances:
            currency = (entry.get("currency") or "*").strip().upper() or "*"
            if currency in seen:
                raise DuplicateCurrencyError(currency)
            seen.add(currency)
            opening = _safe_parse_decimal(entry.get("opening"))
            closing = _safe_parse_decimal(entry.get("closing"))
            if opening is None or closing is None:
                raise ValueError("Printed opening and closing balances are required")
            buckets.append(
                {
                    "currency": currency,
                    "opening": opening,
                    "closing": closing,
                }
            )
        return buckets

    header_currency = (extracted.get("currency") or "*").strip().upper() or "*"
    opening = _safe_parse_decimal(extracted.get("opening_balance"))
    closing = _safe_parse_decimal(extracted.get("closing_balance"))
    if opening is None or closing is None:
        raise ValueError("Printed opening and closing balances are required")
    return [
        {
            "currency": header_currency,
            "opening": opening,
            "closing": closing,
        }
    ]


def validate_balance_per_currency(
    extracted: dict[str, Any], *, tolerance: Decimal = BALANCE_TOLERANCE
) -> dict[str, Any]:
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
            bucket["opening"], bucket["closing"], nets.get(ccy, Decimal("0")), currency=ccy, tolerance=tolerance
        )
        result["currency"] = ccy
        result["declared_balance"] = True
        per_currency.append(result)

    for ccy, net in nets.items():
        if ccy in declared:
            continue
        result = validate_balance_explicit(Decimal("0"), Decimal("0"), net, currency=ccy, tolerance=tolerance)
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
    """Return printed per-currency bank balances when spanning >= 2 currencies, else None."""
    if not isinstance(extracted, dict) or not extracted.get("balances"):
        return None
    buckets = _currency_buckets(extracted)
    if len({bucket["currency"] for bucket in buckets}) < 2:
        return None
    return [
        {"currency": bucket["currency"], "opening": str(bucket["opening"]), "closing": str(bucket["closing"])}
        for bucket in buckets
    ]


def evaluate_statement_balance(
    *,
    opening: Decimal | None,
    closing: Decimal | None,
    currency: str | None,
    currency_balances: list[dict[str, Any]] | None,
    transactions: Sequence[dict[str, Any]],
    tolerance: Decimal = BALANCE_TOLERANCE,
) -> dict[str, Any]:
    """Single canonical balance-equation evaluator shared across parse and approval (#2964)."""
    if currency_balances:
        per_ccy_res = validate_balance_per_currency(
            {"balances": currency_balances, "transactions": list(transactions)}, tolerance=tolerance
        )
        return {
            "balance_valid": per_ccy_res["balance_valid"],
            "balance_computable": per_ccy_res["balance_computable"],
            "balance_proof_available": True,
            "expected_closing": "0",
            "actual_closing": "0",
            "difference": "0.00",
            "per_currency": per_ccy_res.get("per_currency", []),
            "notes": per_ccy_res.get("notes"),
        }
    if opening is None or closing is None:
        return {
            "balance_valid": False,
            "balance_computable": False,
            "balance_proof_available": False,
            "expected_closing": "0",
            "actual_closing": str(closing) if closing is not None else "0",
            "difference": "0",
            "per_currency": [],
            "notes": "Printed opening and closing balances are required",
        }
    net = Decimal("0")
    for txn in transactions:
        raw_amt = _safe_parse_decimal(txn.get("amount"))
        if raw_amt is None:
            return {
                "balance_valid": False,
                "balance_computable": False,
                "balance_proof_available": True,
                "expected_closing": "0",
                "actual_closing": str(closing),
                "difference": "0",
                "per_currency": [],
                "notes": f"Validation error: invalid amount {txn.get('amount')!r}",
            }
        amount, direction = normalize_amount_direction(raw_amt, txn.get("direction"))
        net += amount if direction == "IN" else -amount
    result = validate_balance_explicit(opening, closing, net, currency=currency, tolerance=tolerance)
    result["balance_proof_available"] = True
    result["per_currency"] = []
    return result


def balance_gap_suspect_rows(amounts: Sequence[Decimal], gap: Decimal, limit: int = 5) -> list[int]:
    """Return the indexes of rows whose amount equals the balance gap or half of it.

    A row equal to the gap was dropped. A row equal to half of the gap has a flipped direction.
    """
    return [index for index, amount in enumerate(amounts) if amount in (gap, gap / 2)][:limit]


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
    *,
    tolerance: Decimal = BALANCE_TOLERANCE,
) -> dict[str, Any]:
    expected_closing, diff = balance_check(opening, closing, net_transactions, currency)
    balance_valid = diff <= tolerance
    return {
        "balance_valid": balance_valid,
        "balance_computable": True,
        "expected_closing": str(expected_closing),
        "actual_closing": str(closing),
        "difference": f"{diff:.2f}",
        "raw_difference": str(diff),
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


@dataclass(frozen=True, slots=True)
class ConfidenceBreakdown:
    """Auditable multi-channel confidence calculation using 1 - prod(1 - p_k)."""

    score: int
    combined_probability: Decimal
    active_channels: dict[str, Decimal]
    capped_reason: str | None = None


def _balance_progression_ratio(transactions: Sequence[dict[str, Any]]) -> Decimal:
    balances = []
    for txn in transactions:
        bal, amt = txn.get("balance_after"), txn.get("amount")
        if bal is not None and amt is not None:
            try:
                amount, direction = normalize_amount_direction(
                    Decimal(str(amt)), str(txn.get("direction", "IN")).upper()
                )
                balances.append((Decimal(str(bal)), amount, direction))
            except (ValueError, TypeError, InvalidOperation):
                continue

    if len(balances) < 2:
        return Decimal("0")
    consistent = sum(
        1
        for i in range(1, len(balances))
        if abs(balances[i][0] - (balances[i - 1][0] + (balances[i][1] if balances[i][2] == "IN" else -balances[i][1])))
        <= BALANCE_TOLERANCE
    )
    return Decimal(consistent) / Decimal(len(balances) - 1)


def _currency_consistency_ratio(transactions: Sequence[dict[str, Any]], header_currency: str | None) -> Decimal:
    if not transactions:
        return Decimal("0")
    all_currencies = [txn.get("currency") for txn in transactions]
    non_empty = [c for c in all_currencies if c]
    if not non_empty:
        return Decimal("0")
    target = header_currency or Counter(non_empty).most_common(1)[0][0]
    return Decimal(sum(1 for c in all_currencies if c == target)) / Decimal(len(transactions))


def compute_confidence_breakdown(
    extracted: dict[str, Any],
    balance_result: dict[str, Any],
    missing_fields: list[str] | None = None,
    *,
    is_brokerage: bool = False,
    effective_txn_count: int | None = None,
    source_verified: bool | None = None,
    split_meta_agreed: bool | None = None,
    has_source_fact_gaps: bool = False,
    closing_not_in_source: bool = False,
    has_source_review_reason: bool = False,
) -> ConfidenceBreakdown:
    """Compute auditable confidence (0-100) via 1 - prod(1 - p_k) over independent channels."""
    if missing_fields is None:
        missing_fields = validate_completeness(extracted)

    transactions = extracted.get("transactions", []) or []
    txn_count = len(transactions)

    format_valid = True
    try:
        if extracted.get("period_start"):
            date.fromisoformat(str(extracted["period_start"]))
        if extracted.get("period_end"):
            date.fromisoformat(str(extracted["period_end"]))
        Decimal(str(extracted.get("opening_balance", "0") or "0"))
        Decimal(str(extracted.get("closing_balance", "0") or "0"))
    except (ValueError, TypeError, InvalidOperation):
        format_valid = False

    progression_ratio = _balance_progression_ratio(transactions)
    currency_ratio = _currency_consistency_ratio(transactions, extracted.get("currency"))
    proof_available = balance_result.get("balance_proof_available", True)
    balance_valid = bool(proof_available and balance_result.get("balance_valid"))

    channels: dict[str, Decimal] = {}
    if balance_valid:
        channels["balance_equation"] = CHANNEL_RELIABILITY_BALANCE_EQUATION
    if source_verified is True:
        channels["source_proof"] = CHANNEL_RELIABILITY_SOURCE_PROOF
    if split_meta_agreed is True:
        channels["split_meta"] = CHANNEL_RELIABILITY_SPLIT_META
    if progression_ratio > 0:
        channels["progression"] = CHANNEL_RELIABILITY_PROGRESSION * progression_ratio

    if balance_valid and source_verified is None and format_valid and not missing_fields and txn_count >= 1:
        channels["structure"] = CHANNEL_RELIABILITY_STRUCTURE
    if balance_valid and currency_ratio > 0 and source_verified is None:
        channels["currency"] = Decimal("0.15") * currency_ratio

    error_product = Decimal("1")
    for p_k in channels.values():
        error_product *= Decimal("1") - p_k
    combined = Decimal("1") - error_product

    capped_reason: str | None = None
    if not proof_available:
        raw_score = int((combined * Decimal("100")).quantize(Decimal("1")))
        score = min(raw_score, MISSING_BALANCE_SCORE_CAP)
        capped_reason = "missing_printed_balances"
    elif balance_valid:
        penalties = len(missing_fields) * 5 + (0 if format_valid else 15) + (0 if txn_count >= 1 else 15)
        if txn_count > 500:
            penalties += 5
        score = max(0, min(100, int((combined * Decimal("100")).quantize(Decimal("1"))) - penalties))
    else:
        try:
            diff = Decimal(str(balance_result.get("difference", "0") or "0"))
        except (ValueError, TypeError, InvalidOperation):
            diff = Decimal("999999")
        base_mismatch = 70 if diff <= Decimal("1.00") else (62 if diff <= Decimal("10.00") else 35)
        if not format_valid or txn_count == 0:
            base_mismatch = min(base_mismatch, 45)
        penalty = len(missing_fields) * 4
        score = max(0, min(84, base_mismatch - penalty + int(progression_ratio * Decimal("5"))))
        combined = Decimal(score) / Decimal("100")

    if has_source_fact_gaps or closing_not_in_source or not proof_available:
        score = min(score, MISSING_BALANCE_SCORE_CAP)
        capped_reason = capped_reason or (
            "closing_not_in_source" if closing_not_in_source else "missing_required_source_facts"
        )
    elif source_verified is False or has_source_review_reason:
        score = min(score, UNVERIFIED_SOURCE_SCORE_CAP)
        capped_reason = capped_reason or "unverified_source_modality"

    persisted_count = effective_txn_count if effective_txn_count is not None else txn_count
    if is_brokerage and persisted_count < BROKERAGE_MIN_PLAUSIBLE_TXNS:
        score = min(score, UNDER_EXTRACTION_SCORE_CAP)
        capped_reason = capped_reason or "brokerage_under_extraction"

    return ConfidenceBreakdown(
        score=score,
        combined_probability=combined.quantize(Decimal("0.0001")),
        active_channels=channels,
        capped_reason=capped_reason,
    )


def _sub_account_key(index: int, acct: str | None, currency: str | None, seen: set[str]) -> str:
    """Return '' for primary index 0, and a unique deterministic <=64-char partition key for siblings."""
    if index == 0:
        return ""
    raw = f"{acct or 'acct'}:{(currency or 'multi').upper()}"
    candidate = raw[:64]
    suffix_num = 1
    while candidate in seen:
        tag = f":{index}:{suffix_num}"
        candidate = f"{raw[: 64 - len(tag)]}{tag}"
        suffix_num += 1
    seen.add(candidate)
    return candidate


def split_multi_account_extraction(extracted: dict[str, Any]) -> list[AccountExtractionSlice]:
    """Split a consolidated multi-account payload into 1..N normalized AccountExtractionSlice values."""
    accounts = extracted.get("accounts")
    if isinstance(accounts, list):
        sub_dicts = [dict(item) for item in accounts if isinstance(item, dict)]
        if sub_dicts:
            seen_keys: set[str] = {""}
            slices: list[AccountExtractionSlice] = []
            for idx, sub in enumerate(sub_dicts):
                for inherited in ("institution", "period_start", "period_end"):
                    if sub.get(inherited) is None and extracted.get(inherited) is not None:
                        sub[inherited] = extracted[inherited]
                last4 = sanitize_account_last4(sub.get("account_last4"))
                ccy = str(sub.get("currency") or "").strip().upper() or None
                key = _sub_account_key(idx, last4, ccy, seen_keys)
                analysis = analyze_statement_balance_payload(sub)
                slices.append(AccountExtractionSlice(payload=analysis.payload, sub_account_key=key, analysis=analysis))
            return slices

    analysis = analyze_statement_balance_payload(extracted)
    return [AccountExtractionSlice(payload=analysis.payload, sub_account_key="", analysis=analysis)]

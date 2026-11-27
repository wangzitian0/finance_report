"""Typed statement issue codes, run failure codes, and redacted run diagnostics (L3/L4)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any


class StatementIssueCode(StrEnum):
    """Typed stage-1 review, confirmation, and reporting issue codes."""

    MISSING_INSTITUTION = "MISSING_INSTITUTION"
    MISSING_STATEMENT_CURRENCY = "MISSING_STATEMENT_CURRENCY"
    MISSING_TRANSACTION_CURRENCY = "MISSING_TRANSACTION_CURRENCY"
    MISSING_PERIOD = "MISSING_PERIOD"
    MISSING_BALANCES = "MISSING_BALANCES"
    MISSING_POSITIONS = "MISSING_POSITIONS"
    BALANCE_CHAIN_MISMATCH = "BALANCE_CHAIN_MISMATCH"
    MULTI_ACCOUNT_SUBSECTION = "MULTI_ACCOUNT_SUBSECTION"
    CLOSING_NOT_IN_SOURCE_TEXT = "CLOSING_NOT_IN_SOURCE_TEXT"
    OPENING_NOT_IN_SOURCE_TEXT = "OPENING_NOT_IN_SOURCE_TEXT"
    ROWS_NOT_IN_TEXT = "ROWS_NOT_IN_TEXT"
    UNVERIFIABLE_TEXT_LAYER = "UNVERIFIABLE_TEXT_LAYER"
    ECONOMIC_DISPOSITION_REQUIRED = "ECONOMIC_DISPOSITION_REQUIRED"
    CUSTODY_ACCOUNT_REQUIRED = "CUSTODY_ACCOUNT_REQUIRED"
    LEDGER_EMPTY_NO_DATA = "LEDGER_EMPTY_NO_DATA"
    CROSS_PERIOD_GAP_3198 = "CROSS_PERIOD_GAP_3198"


class RunFailureCode(StrEnum):
    """Lowercase snake_case run failure codes persisted on ``StatementRun.error_code``."""

    PARSE_WALL_CLOCK_TIMEOUT = "parse_wall_clock_timeout"
    PROVIDER_RATE_LIMITED = "provider_rate_limited"
    PROVIDER_TIMEOUT = "provider_timeout"
    INVALID_JSON_PAYLOAD = "invalid_json_payload"
    UNREADABLE_DOCUMENT = "unreadable_document"
    EXTRACTION_REJECTED = "extraction_rejected"
    HEARTBEAT_LOST = "heartbeat_lost"
    CLAIM_TIMEOUT = "claim_timeout"
    DISPATCH_FAILED = "dispatch_failed"
    EXTRACTION_ERROR = "extraction_error"
    CLASSIFICATION_FAILED = "classification_failed"


_FACT_TO_ISSUE_CODE: dict[str, StatementIssueCode] = {
    "institution": StatementIssueCode.MISSING_INSTITUTION,
    "statement_currency": StatementIssueCode.MISSING_STATEMENT_CURRENCY,
    "transaction_currency": StatementIssueCode.MISSING_TRANSACTION_CURRENCY,
    "period": StatementIssueCode.MISSING_PERIOD,
    "balances": StatementIssueCode.MISSING_BALANCES,
    "positions": StatementIssueCode.MISSING_POSITIONS,
}


def classify_run_failure_code(
    *,
    error_type: str | None = None,
    message: str | None = None,
) -> RunFailureCode:
    """Map an extraction exception type and redacted message to a stable ``RunFailureCode``."""
    kind_text = f"{error_type or ''} {message or ''}".lower()
    if "timeout" in kind_text and ("wall_clock" in kind_text or "wall clock" in kind_text):
        return RunFailureCode.PARSE_WALL_CLOCK_TIMEOUT
    if "rate_limit" in kind_text or "ratelimit" in kind_text or "usage_limit" in kind_text or "429" in kind_text:
        return RunFailureCode.PROVIDER_RATE_LIMITED
    if "timeouterror" in kind_text or "(timeout)" in kind_text or "timed out" in kind_text:
        return RunFailureCode.PROVIDER_TIMEOUT
    if "json_parse" in kind_text or "jsondecodeerror" in kind_text or "strict json object" in kind_text:
        return RunFailureCode.INVALID_JSON_PAYLOAD
    if (
        "unreadable" in kind_text
        or "failed to render page" in kind_text
        or "empty pdf" in kind_text
        or "unsupported file type" in kind_text
        or "empty_response" in kind_text
    ):
        return RunFailureCode.UNREADABLE_DOCUMENT
    if "rejected" in kind_text or "quarantined" in kind_text:
        return RunFailureCode.EXTRACTION_REJECTED
    if "dispatch" in kind_text:
        return RunFailureCode.DISPATCH_FAILED
    if "classification" in kind_text:
        return RunFailureCode.CLASSIFICATION_FAILED
    return RunFailureCode.EXTRACTION_ERROR


def classify_statement_issue_codes(
    *,
    missing_facts: Iterable[str] = (),
    balance_validated: bool | None = None,
    has_account: bool = True,
    validation_error: str | None = None,
    rows_not_in_text: Sequence[int] = (),
    closing_not_in_text: bool = False,
    opening_not_in_text: bool = False,
    unverifiable_text_layer: bool = False,
    multi_account_subsection: bool = False,
) -> list[StatementIssueCode]:
    """Derive deterministic, deduplicated ``StatementIssueCode`` values from typed state."""
    ordered: list[StatementIssueCode] = []

    def add(code: StatementIssueCode) -> None:
        if code not in ordered:
            ordered.append(code)

    for fact in missing_facts:
        mapped = _FACT_TO_ISSUE_CODE.get(str(fact))
        if mapped is not None:
            add(mapped)

    if balance_validated is False:
        add(StatementIssueCode.BALANCE_CHAIN_MISMATCH)
    if not has_account:
        add(StatementIssueCode.CUSTODY_ACCOUNT_REQUIRED)
    if closing_not_in_text:
        add(StatementIssueCode.CLOSING_NOT_IN_SOURCE_TEXT)
    if opening_not_in_text:
        add(StatementIssueCode.OPENING_NOT_IN_SOURCE_TEXT)
    if rows_not_in_text:
        add(StatementIssueCode.ROWS_NOT_IN_TEXT)
    if unverifiable_text_layer:
        add(StatementIssueCode.UNVERIFIABLE_TEXT_LAYER)
    if multi_account_subsection:
        add(StatementIssueCode.MULTI_ACCOUNT_SUBSECTION)

    msg = validation_error or ""
    msg_lower = msg.lower()
    if "economic review required:" in msg_lower or "economic disposition" in msg_lower:
        add(StatementIssueCode.ECONOMIC_DISPOSITION_REQUIRED)
    if "balance mismatch" in msg_lower or "balance_mismatch" in msg_lower or "within_doc_collapse" in msg_lower:
        add(StatementIssueCode.BALANCE_CHAIN_MISMATCH)
    if "closing balance" in msg_lower and "not in the document text" in msg_lower:
        add(StatementIssueCode.CLOSING_NOT_IN_SOURCE_TEXT)
    if "opening balance" in msg_lower and "not in the document text" in msg_lower:
        add(StatementIssueCode.OPENING_NOT_IN_SOURCE_TEXT)
    if "rows not found in the document text" in msg_lower:
        add(StatementIssueCode.ROWS_NOT_IN_TEXT)
    if "text layer is unusable" in msg_lower or "no verifiable text layer" in msg_lower:
        add(StatementIssueCode.UNVERIFIABLE_TEXT_LAYER)
    if "several balances" in msg_lower or "several accounts" in msg_lower:
        add(StatementIssueCode.MULTI_ACCOUNT_SUBSECTION)

    return ordered


def _dec_str(value: Decimal | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    return str(value)


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_list(value: Any, *, min_value: int, limit: int) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    result: list[int] = []
    for item in value:
        parsed = _int_or_none(item)
        if parsed is not None and parsed >= min_value:
            result.append(parsed)
        if len(result) >= limit:
            break
    return result


@dataclass(frozen=True, slots=True)
class RunDiagnosticsSnapshot:
    """Typed, PII-free extraction run diagnostics exposed via StatementRunRecord."""

    modality: str | None = None
    page_count: int | None = None
    batch_count: int | None = None
    pass_durations_ms: list[int] = None  # type: ignore[assignment]
    expected_closing: str | None = None
    calculated_closing: str | None = None
    balance_gap: str | None = None
    suspect_row_indices: list[int] = None  # type: ignore[assignment]
    rows_not_in_text_indices: list[int] = None  # type: ignore[assignment]
    issue_codes: list[str] = None  # type: ignore[assignment]
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if self.pass_durations_ms is None:
            object.__setattr__(self, "pass_durations_ms", [])
        if self.suspect_row_indices is None:
            object.__setattr__(self, "suspect_row_indices", [])
        if self.rows_not_in_text_indices is None:
            object.__setattr__(self, "rows_not_in_text_indices", [])
        if self.issue_codes is None:
            object.__setattr__(self, "issue_codes", [])

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> RunDiagnosticsSnapshot | None:
        if not isinstance(raw, Mapping):
            return None
        return cls(
            modality=str(raw["modality"]) if raw.get("modality") else None,
            page_count=_int_or_none(raw.get("page_count")),
            batch_count=_int_or_none(raw.get("batch_count")),
            pass_durations_ms=_int_list(raw.get("pass_durations_ms"), min_value=0, limit=20),
            expected_closing=_dec_str(raw.get("expected_closing")),
            calculated_closing=_dec_str(raw.get("calculated_closing")),
            balance_gap=_dec_str(raw.get("balance_gap")),
            suspect_row_indices=_int_list(raw.get("suspect_row_indices"), min_value=1, limit=50),
            rows_not_in_text_indices=_int_list(raw.get("rows_not_in_text_indices"), min_value=1, limit=50),
            issue_codes=[str(c) for c in (raw.get("issue_codes") or []) if c][:20],
            failure_code=str(raw["failure_code"]) if raw.get("failure_code") else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "modality": self.modality,
            "page_count": self.page_count,
            "batch_count": self.batch_count,
            "pass_durations_ms": list(self.pass_durations_ms),
            "expected_closing": self.expected_closing,
            "calculated_closing": self.calculated_closing,
            "balance_gap": self.balance_gap,
            "suspect_row_indices": list(self.suspect_row_indices),
            "rows_not_in_text_indices": list(self.rows_not_in_text_indices),
            "issue_codes": list(self.issue_codes),
            "failure_code": self.failure_code,
        }


def build_redacted_diagnostics(
    *,
    modality: str | None = None,
    page_count: int | None = None,
    batch_count: int | None = None,
    pass_durations_ms: Sequence[int] = (),
    expected_closing: Decimal | str | None = None,
    calculated_closing: Decimal | str | None = None,
    balance_gap: Decimal | str | None = None,
    suspect_row_indices: Sequence[int] = (),
    rows_not_in_text_indices: Sequence[int] = (),
    issue_codes: Sequence[StatementIssueCode | str] = (),
    failure_code: RunFailureCode | str | None = None,
) -> dict[str, Any]:
    """Build a PII-free, bounded diagnostics dictionary for ``StatementRun.result_summary``."""
    return RunDiagnosticsSnapshot(
        modality=str(modality) if modality else None,
        page_count=_int_or_none(page_count),
        batch_count=_int_or_none(batch_count),
        pass_durations_ms=[max(0, int(ms)) for ms in pass_durations_ms][:20],
        expected_closing=_dec_str(expected_closing),
        calculated_closing=_dec_str(calculated_closing),
        balance_gap=_dec_str(balance_gap),
        suspect_row_indices=[int(idx) for idx in suspect_row_indices if int(idx) >= 1][:50],
        rows_not_in_text_indices=[int(idx) for idx in rows_not_in_text_indices if int(idx) >= 1][:50],
        issue_codes=[code.value if isinstance(code, StatementIssueCode) else str(code) for code in issue_codes][:20],
        failure_code=failure_code.value
        if isinstance(failure_code, RunFailureCode)
        else (str(failure_code) if failure_code else None),
    ).to_dict()


__all__ = [
    "RunDiagnosticsSnapshot",
    "RunFailureCode",
    "StatementIssueCode",
    "build_redacted_diagnostics",
    "classify_run_failure_code",
    "classify_statement_issue_codes",
]

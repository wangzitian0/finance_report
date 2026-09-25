"""CSV parsing (deterministic + AI-assisted)."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from src.extraction.extension._base import (
    ExtractionError,
    _tolerant_parse_date,
    accumulate_stream,
    logger,
    stream_ai_json,
)
from src.extraction.extension.brokerage_positions import (
    UnsupportedBrokerageCsvError,
    classify_brokerage_csv,
    parse_brokerage_csv_payload,
)
from src.observability import detect_pii


@dataclass(frozen=True)
class _BankCsvProfile:
    """Declarative shape of one bank family's transaction CSV export (#2161 G-001).

    The four legacy hand-rolled institution branches (DBS/POSB, Wise,
    OCBC-family, generic fallback) reduce to this table plus the shared row
    loop :func:`_append_bank_csv_rows`; adding an institution means adding a
    profile row, not copying a 50-line loop.
    """

    date_cols: tuple[str, ...]
    debit_cols: tuple[str, ...] = ()
    credit_cols: tuple[str, ...] = ()
    #: how a row's amount/direction is derived:
    #: - "debit_credit": positive debit -> OUT, positive credit -> IN
    #: - "unsigned_direction": amount must be > 0; direction read from a text column
    #: - "signed_or_debit_credit": signed amount column first, debit/credit fallback
    amount_strategy: str = "debit_credit"
    amount_cols: tuple[str, ...] = ()
    direction_cols: tuple[str, ...] = ()
    #: multi-part description: each group resolves to one header; parts are joined
    desc_col_groups: tuple[tuple[str, ...], ...] = ()
    desc_cols: tuple[str, ...] = ()
    desc_default: str = "Transaction"
    #: skip-log description fallback (DBS logs "" here, not "Transaction")
    warn_desc_default: str = "Transaction"
    desc_strip: bool = False
    desc_fallback_on_empty: bool = True
    ref_cols: tuple[str, ...] = ()
    include_reference: bool = True
    #: ISO datetime values carry a "T"; strip the time part before date parsing
    date_time_split: bool = False


@dataclass(frozen=True)
class _ResolvedBankCsvColumns:
    """First-hit header resolution of one profile against a CSV's headers."""

    date: str | None
    debit: str | None
    credit: str | None
    amount: str | None
    direction: str | None
    desc_parts: tuple[str | None, ...]
    desc: str | None
    ref: str | None


_BANK_CSV_PROFILES: tuple[tuple[frozenset[str], _BankCsvProfile], ...] = (
    (
        frozenset({"dbs", "posb"}),
        _BankCsvProfile(
            date_cols=("Transaction Date", "Date", "Value Date"),
            debit_cols=("Debit Amount", "Withdrawal", "Debit"),
            credit_cols=("Credit Amount", "Deposit", "Credit"),
            desc_col_groups=(
                ("Transaction Ref1", "Reference", "Description"),
                ("Transaction Ref2", "Details"),
                ("Transaction Ref3", "Particulars"),
            ),
            desc_default="Transaction",
            warn_desc_default="",
            desc_strip=True,
            desc_fallback_on_empty=True,
            ref_cols=("Reference", "Transaction Reference", "Ref No"),
        ),
    ),
    (
        frozenset({"wise"}),
        _BankCsvProfile(
            date_cols=("Created on", "Date", "Finished on"),
            amount_strategy="unsigned_direction",
            amount_cols=(
                "Source amount (after fees)",
                "Amount",
                "Target amount (after fees)",
            ),
            direction_cols=("Direction", "Type"),
            desc_cols=("Reference", "Description", "Target name", "Source name"),
            desc_default="Wise Transfer",
            warn_desc_default="Wise Transfer",
            desc_strip=False,
            desc_fallback_on_empty=False,
            ref_cols=("ID", "Reference", "TransferWise ID"),
            date_time_split=True,
        ),
    ),
    (
        frozenset({"ocbc", "uob", "standard chartered", "citibank"}),
        _BankCsvProfile(
            date_cols=("Transaction Date", "Date", "Value Date", "Posting Date"),
            debit_cols=("Debit", "Withdrawal", "Debit Amount", "Withdrawals"),
            credit_cols=("Credit", "Deposit", "Credit Amount", "Deposits"),
            desc_cols=(
                "Description",
                "Transaction Description",
                "Particulars",
                "Details",
            ),
            desc_strip=True,
            desc_fallback_on_empty=False,
            ref_cols=("Reference", "Reference No", "Cheque No"),
        ),
    ),
)

_GENERIC_BANK_CSV_PROFILE = _BankCsvProfile(
    date_cols=(
        "date",
        "transaction date",
        "value date",
        "posting date",
        "created on",
    ),
    amount_strategy="signed_or_debit_credit",
    amount_cols=("amount", "value", "sum"),
    debit_cols=("debit", "withdrawal", "debit amount"),
    credit_cols=("credit", "deposit", "credit amount"),
    desc_cols=("description", "details", "particulars", "reference", "memo"),
    desc_strip=True,
    desc_fallback_on_empty=True,
    include_reference=False,
)


def _select_bank_csv_profile(institution_lower: str) -> _BankCsvProfile:
    """Pick the CSV profile for an institution slug (lowercase)."""
    for names, profile in _BANK_CSV_PROFILES:
        if institution_lower in names:
            return profile
    return _GENERIC_BANK_CSV_PROFILE


def _resolve_bank_csv_columns(
    profile: _BankCsvProfile,
    find_header: Callable[[list[str]], str | None],
) -> _ResolvedBankCsvColumns:
    """Resolve a profile's header candidates against the actual CSV headers."""
    return _ResolvedBankCsvColumns(
        date=find_header(list(profile.date_cols)),
        debit=find_header(list(profile.debit_cols)),
        credit=find_header(list(profile.credit_cols)),
        amount=find_header(list(profile.amount_cols)),
        direction=find_header(list(profile.direction_cols)),
        desc_parts=tuple(find_header(list(group)) for group in profile.desc_col_groups),
        desc=find_header(list(profile.desc_cols)),
        ref=find_header(list(profile.ref_cols)),
    )


def _warn_description(
    row: dict[str, Any],
    cols: _ResolvedBankCsvColumns,
    profile: _BankCsvProfile,
) -> str:
    """Description payload for skip warnings (shape preserved per institution)."""
    if profile.desc_col_groups:
        header = cols.desc_parts[0] if cols.desc_parts else None
        return row.get(header, profile.warn_desc_default) if header else profile.warn_desc_default
    if cols.desc:
        return row.get(cols.desc, profile.warn_desc_default)
    return profile.warn_desc_default


def _resolve_row_description(
    row: dict[str, Any],
    cols: _ResolvedBankCsvColumns,
    profile: _BankCsvProfile,
) -> str:
    """Assemble a transaction description per profile semantics."""
    if profile.desc_col_groups:
        parts = [row.get(h, "") for h in cols.desc_parts if h and row.get(h)]
        description: str = " ".join(parts)
    elif cols.desc:
        description = row.get(cols.desc, profile.desc_default)
    else:
        description = profile.desc_default
    if profile.desc_strip:
        description = description.strip()
    if profile.desc_fallback_on_empty and not description:
        description = profile.desc_default
    return description


def _append_bank_csv_rows(
    rows: list[dict[str, Any]],
    cols: _ResolvedBankCsvColumns,
    profile: _BankCsvProfile,
    institution: str,
    parse_date: Callable[[str], date | None],
    parse_amount: Callable[[str], Decimal | None],
    transactions: list[dict[str, Any]],
) -> tuple[date | None, date | None]:
    """Shared transaction-row loop for every bank CSV profile (#2161 G-001).

    Behavior-preserving unification of the four legacy hand-rolled branches;
    skip warnings keep their exact event names and payloads.
    """
    period_start: date | None = None
    period_end: date | None = None

    for row in rows:
        date_raw = row.get(cols.date, "") if cols.date else ""
        if profile.date_time_split and "T" in date_raw:
            date_raw = date_raw.split("T")[0]
        txn_date = parse_date(date_raw) if cols.date else None
        if not txn_date:
            logger.warning(
                "CSV transaction skipped - invalid date",
                institution=institution,
                date_raw=date_raw,
                description=_warn_description(row, cols, profile),
            )
            continue

        warn_desc = _warn_description(row, cols, profile)
        amount: Decimal | None = None
        direction: str | None = None

        if profile.amount_strategy == "debit_credit":
            debit = parse_amount(row.get(cols.debit, "")) if cols.debit else None
            credit = parse_amount(row.get(cols.credit, "")) if cols.credit else None
            if debit and debit > 0:
                amount, direction = debit, "OUT"
            elif credit and credit > 0:
                amount, direction = credit, "IN"
            else:
                logger.warning(
                    "CSV transaction skipped - no valid amount",
                    institution=institution,
                    debit=debit,
                    credit=credit,
                    description=warn_desc,
                )
                continue
        elif profile.amount_strategy == "unsigned_direction":
            amount_raw = row.get(cols.amount, "") if cols.amount else ""
            parsed = parse_amount(amount_raw) if cols.amount else None
            if not parsed or parsed <= 0:
                logger.warning(
                    "CSV transaction skipped - no valid amount",
                    institution=institution,
                    amount_raw=amount_raw,
                    description=warn_desc,
                )
                continue
            amount = parsed
            direction_raw = row.get(cols.direction, "").lower() if cols.direction else ""
            direction = "OUT" if ("out" in direction_raw or "send" in direction_raw) else "IN"
        else:  # "signed_or_debit_credit"
            if cols.amount and row.get(cols.amount):
                parsed = parse_amount(row.get(cols.amount, ""))
                if parsed is None:
                    logger.warning(
                        "CSV transaction skipped - no valid amount",
                        institution=institution,
                        amount_raw=row.get(cols.amount, ""),
                        description=warn_desc,
                    )
                    continue
                direction = "OUT" if parsed < 0 else "IN"
                amount = abs(parsed)
            elif cols.debit or cols.credit:
                debit = parse_amount(row.get(cols.debit, "")) if cols.debit else None
                credit = parse_amount(row.get(cols.credit, "")) if cols.credit else None
                if debit and debit > 0:
                    amount, direction = debit, "OUT"
                elif credit and credit > 0:
                    amount, direction = credit, "IN"
                else:
                    logger.warning(
                        "CSV transaction skipped - no valid amount",
                        institution=institution,
                        debit=debit,
                        credit=credit,
                        description=warn_desc,
                    )
                    continue
            else:
                logger.warning(
                    "CSV transaction skipped - no amount columns found",
                    institution=institution,
                    description=warn_desc,
                )
                continue

        txn: dict[str, Any] = {
            "date": txn_date.isoformat(),
            "amount": str(amount),
            "direction": direction,
            "description": _resolve_row_description(row, cols, profile),
        }
        if profile.include_reference:
            txn["reference"] = row.get(cols.ref, "") if cols.ref else None
        transactions.append(txn)

        if period_start is None or txn_date < period_start:
            period_start = txn_date
        if period_end is None or txn_date > period_end:
            period_end = txn_date

    return period_start, period_end


class _CsvMixin:
    api_key: str | None
    primary_model: str

    async def _parse_csv_content(self, file_content: bytes | str, institution: str) -> dict[str, Any]:
        """Parse CSV content directly from bytes or string.

        Supports multiple bank formats with auto-detection and AI fallback.
        """
        import csv
        import io

        if isinstance(file_content, bytes):
            text = file_content.decode(encoding="utf-8-sig", errors="ignore")
        else:
            text = file_content.lstrip("\ufeff")

        pii_matches = detect_pii(text)
        if pii_matches:
            logger.warning(
                "PII detected in CSV content",
                pii_count=len(pii_matches),
                pii_types=list({m.pii_type.value for m in pii_matches}),
                institution=institution,
            )

        reader = csv.DictReader(io.StringIO(text))

        rows = list(reader)
        if not rows:
            raise ExtractionError("CSV file is empty or has no data rows")

        headers = list(reader.fieldnames or [])
        headers_lower = [h.lower().strip() for h in headers]
        institution_lower = institution.lower()

        # Brokerage CSV routing (#1255): bank CSV parsing below only understands
        # bank transaction schemas (date/description/amount/debit/credit/balance).
        # Brokerage CSVs use different schemas, so detect them BEFORE bank parsing.
        # The decisive signal is the header SHAPE (classify_brokerage_csv), not the
        # broker name: a known broker can still export a bank-style transaction CSV,
        # which must keep flowing through bank parsing. A positions/holdings CSV is
        # mapped into a brokerage ``positions`` payload (flows into
        # BrokeragePositionImportService via looks_like_brokerage_payload); a
        # trade-history CSV is rejected with an actionable error rather than the
        # misleading generic bank "No valid transactions found" failure.
        if classify_brokerage_csv(headers):
            try:
                brokerage_payload = parse_brokerage_csv_payload(headers, rows, institution=institution)
            except UnsupportedBrokerageCsvError as exc:
                logger.warning(
                    "Brokerage CSV rejected as unsupported",
                    institution=institution,
                    headers=headers,
                    reason=str(exc),
                )
                raise ExtractionError(str(exc)) from exc
            logger.info(
                "Brokerage positions CSV parsed",
                institution=institution,
                positions_count=len(brokerage_payload.get("positions", [])),
            )
            return brokerage_payload

        transactions: list[dict[str, Any]] = []
        period_start: date | None = None
        period_end: date | None = None

        def parse_date(value: str) -> date | None:
            """Parse a CSV date via the shared tolerant parser (#1086)."""
            return _tolerant_parse_date(value)

        def parse_amount(value: str) -> Decimal | None:
            """Parse amount string to Decimal."""
            if not value or not value.strip():
                return None
            cleaned = value.strip().replace(",", "").replace("$", "").replace("SGD", "").replace("USD", "").strip()
            if not cleaned or cleaned == "-":
                return None
            try:
                return Decimal(cleaned)
            except (ValueError, InvalidOperation):
                return None

        def find_header(candidates: list[str]) -> str | None:
            for candidate in candidates:
                if candidate.lower() in headers_lower:
                    idx = headers_lower.index(candidate.lower())
                    return headers[idx]
            return None

        def declared_statement_fact(
            label: str,
            candidates: list[str],
            parse,
        ) -> Any | None:
            """Read one redundant CSV statement-envelope column without inference.

            A transaction export remains row evidence. A CSV becomes a statement
            source only when it repeats an explicit envelope fact consistently
            across its rows; conflicting declarations are malformed source data.
            """
            header = find_header(candidates)
            if header is None:
                return None
            values = [str(row[header]).strip() for row in rows if row.get(header) and str(row[header]).strip()]
            if not values:
                return None
            parsed = [parse(value) for value in values]
            if any(value is None for value in parsed):
                raise ExtractionError(f"CSV has an invalid declared {label}")
            unique = {value for value in parsed if value is not None}
            if len(unique) != 1:
                raise ExtractionError(f"CSV has conflicting declared {label}")
            return next(iter(unique))

        source_currency = declared_statement_fact(
            "statement currency",
            ["Statement Currency"],
            lambda value: value.upper() if len(value) == 3 and value.isalpha() else None,
        )
        source_period_start = declared_statement_fact(
            "statement period start",
            ["Statement Period Start"],
            parse_date,
        )
        source_period_end = declared_statement_fact(
            "statement period end",
            ["Statement Period End"],
            parse_date,
        )
        source_opening_balance = declared_statement_fact(
            "statement opening balance",
            ["Statement Opening Balance"],
            parse_amount,
        )
        source_closing_balance = declared_statement_fact(
            "statement closing balance",
            ["Statement Closing Balance"],
            parse_amount,
        )

        profile = _select_bank_csv_profile(institution_lower)
        cols = _resolve_bank_csv_columns(profile, find_header)
        period_start, period_end = _append_bank_csv_rows(
            rows=rows,
            cols=cols,
            profile=profile,
            institution=institution,
            parse_date=parse_date,
            parse_amount=parse_amount,
            transactions=transactions,
        )

        used_ai_mapping = False
        if not transactions:
            # EPIC-018 Phase 4: AI CSV parsing fallback for unknown formats
            logger.info(
                "No transactions from heuristic parsing, trying AI CSV mapping",
                institution=institution,
                headers=headers,
            )
            try:
                transactions, period_start, period_end = await self._ai_parse_csv(
                    headers,
                    rows,
                    institution,
                    parse_date,
                    parse_amount,
                )
                used_ai_mapping = bool(transactions)
            except Exception as ai_err:
                logger.warning(
                    "AI CSV parsing fallback failed",
                    error=str(ai_err),
                    error_type=type(ai_err).__name__,
                    institution=institution,
                )

        if not transactions:
            logger.warning(
                "CSV parsing found no valid transactions",
                institution=institution,
                headers=headers,
                row_count=len(rows),
            )
            raise ExtractionError(f"No valid transactions found in CSV for {institution}")

        logger.info(
            "CSV parsing completed",
            institution=institution,
            transactions_count=len(transactions),
            period_start=period_start.isoformat() if period_start else None,
            period_end=period_end.isoformat() if period_end else None,
        )

        source_facts: dict[str, Any] = {}
        if source_currency is not None:
            source_facts["currency"] = source_currency
        if source_period_start is not None:
            source_facts["period_start"] = source_period_start.isoformat()
        if source_period_end is not None:
            source_facts["period_end"] = source_period_end.isoformat()
        if source_opening_balance is not None:
            source_facts["opening_balance"] = str(source_opening_balance)
        if source_closing_balance is not None:
            source_facts["closing_balance"] = str(source_closing_balance)

        return {
            **source_facts,
            # A transaction export does not prove statement currency, period, or
            # opening/closing balances. Keep those facts absent instead of
            # laundering SGD/zero/net-flow defaults into the trusted envelope.
            "balance_source": "missing_from_csv_export",
            "observed_transaction_start": period_start.isoformat() if period_start else None,
            "observed_transaction_end": period_end.isoformat() if period_end else None,
            "extraction_method": "live_llm" if used_ai_mapping else "deterministic",
            "transactions": transactions,
        }

    async def _ai_parse_csv(
        self,
        headers: list[str],
        rows: list[dict],
        institution: str,
        parse_date,
        parse_amount,
    ) -> tuple[list[dict], date | None, date | None]:
        """EPIC-018 Phase 4: AI-powered CSV column mapping for unknown institutions.

        Uses AI to identify which columns contain date, description, amount, etc.
        Returns (transactions, period_start, period_end).
        """

        from src.extraction.extension.prompts.csv_mapping import build_csv_mapping_prompt

        if not self.api_key:
            raise ExtractionError("AI provider API key required for AI CSV parsing")

        # Build sample rows for the prompt
        sample_rows = []
        for row in rows[:5]:
            sample_rows.append([row.get(h, "") for h in headers])

        prompt = build_csv_mapping_prompt(headers, sample_rows)
        messages = [{"role": "user", "content": prompt}]

        stream = stream_ai_json(
            messages=messages,
            model=self.primary_model,
            timeout=30.0,
        )
        content = await accumulate_stream(stream)

        if not content or not content.strip():
            raise ExtractionError("AI CSV mapping returned empty response")

        mapping = json.loads(content)

        date_col = mapping.get("date")
        desc_col = mapping.get("description")
        amount_col = mapping.get("amount")
        debit_col = mapping.get("debit")
        credit_col = mapping.get("credit")

        logger.info(
            "AI CSV column mapping identified",
            institution=institution,
            mapping=mapping,
        )

        transactions: list[dict] = []
        period_start: date | None = None
        period_end: date | None = None

        for row in rows:
            txn_date = parse_date(row.get(date_col, "")) if date_col else None
            if not txn_date:
                continue

            if amount_col and row.get(amount_col):
                amount = parse_amount(row.get(amount_col, ""))
                if amount is not None:
                    direction = "OUT" if amount < 0 else "IN"
                    amount = abs(amount)
                else:
                    continue
            elif debit_col or credit_col:
                debit = parse_amount(row.get(debit_col, "")) if debit_col else None
                credit = parse_amount(row.get(credit_col, "")) if credit_col else None
                if debit and debit > 0:
                    amount = debit
                    direction = "OUT"
                elif credit and credit > 0:
                    amount = credit
                    direction = "IN"
                else:
                    continue
            else:
                continue

            description = row.get(desc_col, "Transaction") if desc_col else "Transaction"

            transactions.append(
                {
                    "date": txn_date.isoformat(),
                    "amount": str(amount),
                    "direction": direction,
                    "description": description.strip() if description else "Transaction",
                }
            )

            if period_start is None or txn_date < period_start:
                period_start = txn_date
            if period_end is None or txn_date > period_end:
                period_end = txn_date

        logger.info(
            "AI CSV parsing completed",
            institution=institution,
            transactions_count=len(transactions),
        )

        return transactions, period_start, period_end

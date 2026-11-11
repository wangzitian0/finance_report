"""CSV parsing (deterministic + AI-assisted)."""

import csv
import io
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
    """Declarative shape of one bank family's transaction CSV export."""

    date_cols: tuple[str, ...]
    debit_cols: tuple[str, ...] = ()
    credit_cols: tuple[str, ...] = ()
    amount_strategy: str = "debit_credit"
    amount_cols: tuple[str, ...] = ()
    direction_cols: tuple[str, ...] = ()
    desc_col_groups: tuple[tuple[str, ...], ...] = ()
    desc_cols: tuple[str, ...] = ()
    desc_default: str = "Transaction"
    warn_desc_default: str = "Transaction"
    desc_strip: bool = False
    desc_fallback_on_empty: bool = True
    ref_cols: tuple[str, ...] = ()
    include_reference: bool = True
    date_time_split: bool = False
    currency_cols: tuple[str, ...] = ("Currency", "Transaction Currency", "CCY")
    balance_cols: tuple[str, ...] = ("Balance", "Running Balance", "Ledger Balance", "Available Balance")


@dataclass(frozen=True)
class _ResolvedBankCsvColumns:
    date: str | None
    debit: str | None
    credit: str | None
    amount: str | None
    direction: str | None
    desc_parts: tuple[str | None, ...] = ()
    desc: str | None = None
    ref: str | None = None
    currency: str | None = None
    balance: str | None = None


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
            amount_cols=("Source amount (after fees)", "Amount", "Target amount (after fees)"),
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
            desc_cols=("Description", "Transaction Description", "Particulars", "Details"),
            desc_strip=True,
            desc_fallback_on_empty=False,
            ref_cols=("Reference", "Reference No", "Cheque No"),
        ),
    ),
    (
        frozenset({"wechat", "wechat_pay", "wechat pay", "weixin"}),
        _BankCsvProfile(
            date_cols=("交易时间", "时间", "Date", "Transaction Date"),
            amount_strategy="unsigned_direction",
            amount_cols=("金额(元)", "金额", "Amount"),
            direction_cols=("收/支", "收支", "Type", "Direction"),
            desc_cols=("交易对方", "商品", "交易类型", "Description"),
            desc_col_groups=(("交易对方", "Counterparty"), ("商品", "Product"), ("交易类型", "Type")),
            desc_default="WeChat Pay Transaction",
            warn_desc_default="WeChat Pay Transaction",
            desc_strip=True,
            desc_fallback_on_empty=True,
            ref_cols=("交易单号", "商户单号", "Reference"),
        ),
    ),
    (
        frozenset({"alipay", "ali_pay", "alipay.com", "zhifubao"}),
        _BankCsvProfile(
            date_cols=("交易时间", "时间", "Date", "Transaction Date"),
            amount_strategy="unsigned_direction",
            amount_cols=("金额", "金额(元)", "Amount"),
            direction_cols=("收/支", "收支", "Type", "Direction"),
            desc_cols=("交易对方", "商品说明", "交易分类", "Description"),
            desc_col_groups=(("交易对方", "Counterparty"), ("商品说明", "Product"), ("交易分类", "Category")),
            desc_default="Alipay Transaction",
            warn_desc_default="Alipay Transaction",
            desc_strip=True,
            desc_fallback_on_empty=True,
            ref_cols=("交易订单号", "商家订单号", "Reference"),
        ),
    ),
)

_GENERIC_BANK_CSV_PROFILE = _BankCsvProfile(
    date_cols=("date", "transaction date", "value date", "posting date", "created on"),
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
    for names, profile in _BANK_CSV_PROFILES:
        if institution_lower in names:
            return profile
    return _GENERIC_BANK_CSV_PROFILE


def _resolve_bank_csv_columns(
    profile: _BankCsvProfile,
    find_header: Callable[[list[str]], str | None],
) -> _ResolvedBankCsvColumns:
    return _ResolvedBankCsvColumns(
        date=find_header(list(profile.date_cols)),
        debit=find_header(list(profile.debit_cols)),
        credit=find_header(list(profile.credit_cols)),
        amount=find_header(list(profile.amount_cols)),
        direction=find_header(list(profile.direction_cols)),
        desc_parts=tuple(find_header(list(group)) for group in profile.desc_col_groups),
        desc=find_header(list(profile.desc_cols)),
        ref=find_header(list(profile.ref_cols)),
        currency=find_header(list(profile.currency_cols)),
        balance=find_header(list(profile.balance_cols)),
    )


def _warn_description(row: dict[str, Any], cols: _ResolvedBankCsvColumns, profile: _BankCsvProfile) -> str:
    if profile.desc_col_groups:
        header = cols.desc_parts[0] if cols.desc_parts else None
        return row.get(header, profile.warn_desc_default) if header else profile.warn_desc_default
    return row.get(cols.desc, profile.warn_desc_default) if cols.desc else profile.warn_desc_default


def _resolve_row_description(row: dict[str, Any], cols: _ResolvedBankCsvColumns, profile: _BankCsvProfile) -> str:
    if profile.desc_col_groups:
        description = " ".join(row.get(h, "") for h in cols.desc_parts if h and row.get(h))
    elif cols.desc:
        description = row.get(cols.desc, profile.desc_default) or ""
    else:
        description = profile.desc_default
    if profile.desc_strip:
        description = description.strip()
    if profile.desc_fallback_on_empty and not description:
        description = profile.desc_default
    return description


def _resolve_debit_credit(
    row: dict[str, Any],
    cols: _ResolvedBankCsvColumns,
    parse_amount: Callable[[str], Decimal | None],
) -> tuple[Decimal | None, str | None, Decimal | None, Decimal | None]:
    debit = parse_amount(row.get(cols.debit, "")) if cols.debit else None
    credit = parse_amount(row.get(cols.credit, "")) if cols.credit else None
    if debit and debit > 0:
        return debit, "OUT", debit, credit
    if credit and credit > 0:
        return credit, "IN", debit, credit
    return None, None, debit, credit


def _append_bank_csv_rows(
    rows: list[dict[str, Any]],
    cols: _ResolvedBankCsvColumns,
    profile: _BankCsvProfile,
    institution: str,
    parse_date: Callable[[str], date | None],
    parse_amount: Callable[[str], Decimal | None],
    transactions: list[dict[str, Any]],
    *,
    emit_skip_warnings: bool = True,
) -> tuple[date | None, date | None]:
    """Shared transaction-row loop for deterministic and AI-mapped bank CSV profiles."""
    period_start: date | None = None
    period_end: date | None = None

    for row in rows:
        date_raw = (row.get(cols.date, "") if cols.date else "")
        if emit_skip_warnings:
            date_raw = date_raw.strip()
        if profile.date_time_split and "T" in date_raw:
            date_raw = date_raw.split("T")[0]
        txn_date = parse_date(date_raw) if cols.date else None
        if not txn_date:
            if emit_skip_warnings:
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
            amount, direction, debit, credit = _resolve_debit_credit(row, cols, parse_amount)
            if amount is None:
                if emit_skip_warnings:
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
                if emit_skip_warnings:
                    logger.warning(
                        "CSV transaction skipped - no valid amount",
                        institution=institution,
                        amount_raw=amount_raw,
                        description=warn_desc,
                    )
                continue
            amount = parsed
            direction_raw = (row.get(cols.direction, "") if cols.direction else "").strip().lower()
            if "不计收支" in direction_raw or "其他" in direction_raw or direction_raw == "/":
                if emit_skip_warnings:
                    logger.info(
                        "CSV non-monetary or excluded row skipped",
                        institution=institution,
                        direction_raw=direction_raw,
                        description=warn_desc,
                    )
                continue
            direction = "OUT" if ("out" in direction_raw or "send" in direction_raw or "支" in direction_raw) else "IN"
        else:  # "signed_or_debit_credit"
            if cols.amount and row.get(cols.amount):
                parsed = parse_amount(row.get(cols.amount, ""))
                if parsed is None:
                    if emit_skip_warnings:
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
                amount, direction, debit, credit = _resolve_debit_credit(row, cols, parse_amount)
                if amount is None:
                    if emit_skip_warnings:
                        logger.warning(
                            "CSV transaction skipped - no valid amount",
                            institution=institution,
                            debit=debit,
                            credit=credit,
                            description=warn_desc,
                        )
                    continue
            else:
                if emit_skip_warnings:
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
            ref_val = row.get(cols.ref, "") if cols.ref else ""
            txn["reference"] = str(ref_val).strip() if ref_val else None
        if cols.currency:
            ccy_raw = str(row.get(cols.currency, "") or "").strip().upper()
            if len(ccy_raw) == 3 and ccy_raw.isalpha():
                txn["currency"] = ccy_raw
        if cols.balance:
            bal_val = parse_amount(str(row.get(cols.balance, "") or ""))
            if bal_val is not None:
                txn["balance_after"] = str(bal_val)
        transactions.append(txn)

        if period_start is None or txn_date < period_start:
            period_start = txn_date
        if period_end is None or txn_date > period_end:
            period_end = txn_date

    return period_start, period_end


def _strip_csv_preamble(text: str) -> str:
    lines = text.splitlines(keepends=True)
    candidate_headers = (
        "transaction date",
        "交易时间",
        "date",
        "posting date",
        "value date",
        "created on",
        "statement currency",
    )
    for idx, line in enumerate(lines[:50]):
        line_lower = line.lower()
        if any(h in line_lower for h in candidate_headers):
            return "".join(lines[idx:])
    return text


class _CsvMixin:
    api_key: str | None
    small_model: str

    async def _parse_csv_content(self, file_content: bytes | str, institution: str) -> dict[str, Any]:
        """Parse CSV content from bytes or string with brokerage routing and AI fallback."""
        if isinstance(file_content, bytes):
            for encoding in ("utf-8-sig", "gb18030"):
                try:
                    text = file_content.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                text = file_content.decode("utf-8-sig", errors="ignore")
        else:
            text = file_content.lstrip("\ufeff")

        text = _strip_csv_preamble(text)
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

        def parse_date(value: str) -> date | None:
            return _tolerant_parse_date(value)

        def parse_amount(value: str) -> Decimal | None:
            if not value or not value.strip():
                return None
            cleaned = value.strip()
            for token in (",", "$", "SGD", "USD", "¥", "￥", "元"):
                cleaned = cleaned.replace(token, "")
            cleaned = cleaned.strip()
            if not cleaned or cleaned == "-":
                return None
            try:
                return Decimal(cleaned)
            except (ValueError, InvalidOperation):
                return None

        def find_header(candidates: list[str]) -> str | None:
            for candidate in candidates:
                if candidate.lower() in headers_lower:
                    return headers[headers_lower.index(candidate.lower())]
            return None

        def declared_statement_fact(label: str, candidates: list[str], parse) -> Any | None:
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
            "statement currency", ["Statement Currency"], lambda v: v.upper() if len(v) == 3 and v.isalpha() else None
        )
        source_period_start = declared_statement_fact("statement period start", ["Statement Period Start"], parse_date)
        source_period_end = declared_statement_fact("statement period end", ["Statement Period End"], parse_date)
        source_opening_balance = declared_statement_fact(
            "statement opening balance", ["Statement Opening Balance"], parse_amount
        )
        source_closing_balance = declared_statement_fact(
            "statement closing balance", ["Statement Closing Balance"], parse_amount
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
        if source_currency is None and transactions:
            txn_currencies = [txn.get("currency") for txn in transactions]
            if all(isinstance(ccy, str) and len(ccy) == 3 for ccy in txn_currencies) and len(set(txn_currencies)) == 1:
                source_currency = str(txn_currencies[0])

        used_ai_mapping = False
        if not transactions:
            logger.info("No transactions from heuristic parsing, trying AI CSV mapping", institution=institution, headers=headers)
            try:
                transactions, period_start, period_end = await self._ai_parse_csv(
                    headers, rows, institution, parse_date, parse_amount
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
            logger.warning("CSV parsing found no valid transactions", institution=institution, headers=headers, row_count=len(rows))
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

        balances_declared = source_opening_balance is not None and source_closing_balance is not None
        return {
            **source_facts,
            "balance_source": "declared_in_csv_export" if balances_declared else "missing_from_csv_export",
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
        """AI-powered CSV column mapping fallback for unknown institutions."""
        from src.extraction.extension.prompts.csv_mapping import build_csv_mapping_prompt

        if not self.api_key:
            raise ExtractionError("AI provider API key required for AI CSV parsing")

        sample_rows = [[row.get(h, "") for h in headers] for row in rows[:5]]
        prompt = build_csv_mapping_prompt(headers, sample_rows)
        stream = stream_ai_json(messages=[{"role": "user", "content": prompt}], model=self.small_model, timeout=30.0)
        content = await accumulate_stream(stream)
        if not content or not content.strip():
            raise ExtractionError("AI CSV mapping returned empty response")

        mapping = json.loads(content)
        logger.info("AI CSV column mapping identified", institution=institution, mapping=mapping)

        cols = _ResolvedBankCsvColumns(
            date=mapping.get("date"),
            debit=mapping.get("debit"),
            credit=mapping.get("credit"),
            amount=mapping.get("amount"),
            direction=None,
            desc=mapping.get("description"),
        )
        transactions: list[dict] = []
        period_start, period_end = _append_bank_csv_rows(
            rows=rows,
            cols=cols,
            profile=_GENERIC_BANK_CSV_PROFILE,
            institution=institution,
            parse_date=parse_date,
            parse_amount=parse_amount,
            transactions=transactions,
            emit_skip_warnings=False,
        )
        logger.info("AI CSV parsing completed", institution=institution, transactions_count=len(transactions))
        return transactions, period_start, period_end

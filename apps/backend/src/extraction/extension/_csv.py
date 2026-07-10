"""CSV parsing (deterministic + AI-assisted)."""

import json
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


class _CsvMixin:
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

        if institution_lower in ("dbs", "posb"):
            date_col = find_header(["Transaction Date", "Date", "Value Date"])
            debit_col = find_header(["Debit Amount", "Withdrawal", "Debit"])
            credit_col = find_header(["Credit Amount", "Deposit", "Credit"])
            desc_cols = [
                find_header(["Transaction Ref1", "Reference", "Description"]),
                find_header(["Transaction Ref2", "Details"]),
                find_header(["Transaction Ref3", "Particulars"]),
            ]
            ref_col = find_header(["Reference", "Transaction Reference", "Ref No"])

            for row in rows:
                txn_date = parse_date(row.get(date_col, "")) if date_col else None
                if not txn_date:
                    logger.warning(
                        "CSV transaction skipped - invalid date",
                        institution=institution,
                        date_raw=row.get(date_col, ""),
                        description=row.get(desc_cols[0] if desc_cols else None, ""),
                    )
                    continue

                debit = parse_amount(row.get(debit_col, "")) if debit_col else None
                credit = parse_amount(row.get(credit_col, "")) if credit_col else None

                if debit and debit > 0:
                    amount = debit
                    direction = "OUT"
                elif credit and credit > 0:
                    amount = credit
                    direction = "IN"
                else:
                    logger.warning(
                        "CSV transaction skipped - no valid amount",
                        institution=institution,
                        debit=debit,
                        credit=credit,
                        description=row.get(desc_cols[0] if desc_cols else None, ""),
                    )
                    continue

                desc_parts = [row.get(col, "") for col in desc_cols if col and row.get(col)]
                description = " ".join(desc_parts).strip() or "Transaction"

                transactions.append(
                    {
                        "date": txn_date.isoformat(),
                        "amount": str(amount),
                        "direction": direction,
                        "description": description,
                        "reference": row.get(ref_col, "") if ref_col else None,
                    }
                )

                if period_start is None or txn_date < period_start:
                    period_start = txn_date
                if period_end is None or txn_date > period_end:
                    period_end = txn_date

        elif institution_lower == "wise":
            date_col = find_header(["Created on", "Date", "Finished on"])
            amount_col = find_header(["Source amount (after fees)", "Amount", "Target amount (after fees)"])
            direction_col = find_header(["Direction", "Type"])
            desc_col = find_header(["Reference", "Description", "Target name", "Source name"])
            ref_col = find_header(["ID", "Reference", "TransferWise ID"])

            for row in rows:
                date_str = row.get(date_col, "") if date_col else ""
                if "T" in date_str:
                    date_str = date_str.split("T")[0]
                txn_date = parse_date(date_str)
                if not txn_date:
                    logger.warning(
                        "CSV transaction skipped - invalid date",
                        institution=institution,
                        date_raw=date_str,
                        description=row.get(desc_col, "Wise Transfer"),
                    )
                    continue

                amount = parse_amount(row.get(amount_col, "")) if amount_col else None
                if not amount or amount <= 0:
                    logger.warning(
                        "CSV transaction skipped - no valid amount",
                        institution=institution,
                        amount_raw=row.get(amount_col, ""),
                        description=row.get(desc_col, "Wise Transfer"),
                    )
                    continue

                direction_raw = row.get(direction_col, "").lower() if direction_col else ""
                if "out" in direction_raw or "send" in direction_raw:
                    direction = "OUT"
                else:
                    direction = "IN"

                description = row.get(desc_col, "Wise Transfer") if desc_col else "Wise Transfer"

                transactions.append(
                    {
                        "date": txn_date.isoformat(),
                        "amount": str(amount),
                        "direction": direction,
                        "description": description,
                        "reference": row.get(ref_col, "") if ref_col else None,
                    }
                )

                if period_start is None or txn_date < period_start:
                    period_start = txn_date
                if period_end is None or txn_date > period_end:
                    period_end = txn_date

        elif institution_lower in ("ocbc", "uob", "standard chartered", "citibank"):
            date_col = find_header(["Transaction Date", "Date", "Value Date", "Posting Date"])
            debit_col = find_header(["Debit", "Withdrawal", "Debit Amount", "Withdrawals"])
            credit_col = find_header(["Credit", "Deposit", "Credit Amount", "Deposits"])
            desc_col = find_header(["Description", "Transaction Description", "Particulars", "Details"])
            ref_col = find_header(["Reference", "Reference No", "Cheque No"])

            for row in rows:
                txn_date = parse_date(row.get(date_col, "")) if date_col else None
                if not txn_date:
                    logger.warning(
                        "CSV transaction skipped - invalid date",
                        institution=institution,
                        date_raw=row.get(date_col, ""),
                        description=row.get(desc_col, "Transaction") if desc_col else "Transaction",
                    )
                    continue

                debit = parse_amount(row.get(debit_col, "")) if debit_col else None
                credit = parse_amount(row.get(credit_col, "")) if credit_col else None

                if debit and debit > 0:
                    amount = debit
                    direction = "OUT"
                elif credit and credit > 0:
                    amount = credit
                    direction = "IN"
                else:
                    logger.warning(
                        "CSV transaction skipped - no valid amount",
                        institution=institution,
                        debit=debit,
                        credit=credit,
                        description=row.get(desc_col, "Transaction") if desc_col else "Transaction",
                    )
                    continue

                description = row.get(desc_col, "Transaction") if desc_col else "Transaction"

                transactions.append(
                    {
                        "date": txn_date.isoformat(),
                        "amount": str(amount),
                        "direction": direction,
                        "description": description.strip(),
                        "reference": row.get(ref_col, "") if ref_col else None,
                    }
                )

                if period_start is None or txn_date < period_start:
                    period_start = txn_date
                if period_end is None or txn_date > period_end:
                    period_end = txn_date

        else:
            date_col = find_header(["date", "transaction date", "value date", "posting date", "created on"])
            amount_col = find_header(["amount", "value", "sum"])
            debit_col = find_header(["debit", "withdrawal", "debit amount"])
            credit_col = find_header(["credit", "deposit", "credit amount"])
            desc_col = find_header(["description", "details", "particulars", "reference", "memo"])

            for row in rows:
                txn_date = parse_date(row.get(date_col, "")) if date_col else None
                if not txn_date:
                    logger.warning(
                        "CSV transaction skipped - invalid date",
                        institution=institution,
                        date_raw=row.get(date_col, ""),
                        description=row.get(desc_col, "Transaction") if desc_col else "Transaction",
                    )
                    continue

                if amount_col and row.get(amount_col):
                    amount = parse_amount(row.get(amount_col, ""))
                    if amount is not None:
                        direction = "OUT" if amount < 0 else "IN"
                        amount = abs(amount)
                    else:
                        logger.warning(
                            "CSV transaction skipped - no valid amount",
                            institution=institution,
                            amount_raw=row.get(amount_col, ""),
                            description=row.get(desc_col, "Transaction") if desc_col else "Transaction",
                        )
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
                        logger.warning(
                            "CSV transaction skipped - no valid amount",
                            institution=institution,
                            debit=debit,
                            credit=credit,
                            description=row.get(desc_col, "Transaction") if desc_col else "Transaction",
                        )
                        continue
                else:
                    logger.warning(
                        "CSV transaction skipped - no amount columns found",
                        institution=institution,
                        description=row.get(desc_col, "Transaction") if desc_col else "Transaction",
                    )
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

        inferred_closing_balance = sum(
            (
                Decimal(str(txn["amount"])) if txn.get("direction") == "IN" else -Decimal(str(txn["amount"]))
                for txn in transactions
            ),
            Decimal("0.00"),
        )

        logger.info(
            "CSV parsing completed",
            institution=institution,
            transactions_count=len(transactions),
            period_start=period_start.isoformat() if period_start else None,
            period_end=period_end.isoformat() if period_end else None,
        )

        return {
            "currency": "SGD",
            "period_start": period_start.isoformat() if period_start else None,
            "period_end": period_end.isoformat() if period_end else None,
            "opening_balance": "0.00",
            "closing_balance": str(inferred_closing_balance),
            "balance_source": "inferred_from_csv_transactions",
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

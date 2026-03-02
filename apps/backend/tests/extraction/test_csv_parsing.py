"""Tests for CSV statement parsing logic."""

import pytest

from src.services.extraction import ExtractionError, ExtractionService


class TestCSVParsing:
    def setup_method(self):
        self.service = ExtractionService()

    @pytest.mark.asyncio
    async def test_parse_dbs_csv(self):
        """[AC3.1.2] Parse DBS CSV format."""
        csv_content = b"""Transaction Date,Reference,Debit Amount,Credit Amount,Transaction Ref1,Transaction Ref2,Transaction Ref3
15 Jan 2025,REF001,,500.00,SALARY,EMPLOYER PTE LTD,JAN 2025
16 Jan 2025,REF002,100.00,,NETS,FAIRPRICE,GROCERIES
17 Jan 2025,REF003,50.00,,ATM WITHDRAWAL,DBS ATM,"""

        result = await self.service._parse_csv_content(csv_content, "DBS")

        assert result["currency"] == "SGD"
        assert result["period_start"] == "2025-01-15"
        assert result["period_end"] == "2025-01-17"
        assert len(result["transactions"]) == 3

        txn0 = result["transactions"][0]
        assert txn0["date"] == "2025-01-15"
        assert txn0["amount"] == "500.00"
        assert txn0["direction"] == "IN"
        assert "SALARY" in txn0["description"]

        txn1 = result["transactions"][1]
        assert txn1["direction"] == "OUT"
        assert txn1["amount"] == "100.00"

    @pytest.mark.asyncio
    async def test_parse_posb_csv(self):
        csv_content = b"""Transaction Date,Debit Amount,Credit Amount,Transaction Ref1
20 Jan 2025,,1000.00,TRANSFER FROM SAVINGS
21 Jan 2025,200.00,,BILL PAYMENT"""

        result = await self.service._parse_csv_content(csv_content, "POSB")

        assert len(result["transactions"]) == 2
        assert result["transactions"][0]["direction"] == "IN"
        assert result["transactions"][1]["direction"] == "OUT"

    @pytest.mark.asyncio
    async def test_parse_wise_csv(self):
        """[AC3.1.3] Parse Wise CSV format."""
        csv_content = b"""ID,Created on,Direction,Source amount (after fees),Reference
12345,2025-01-10T10:30:00Z,OUT,250.00,Payment to vendor
12346,2025-01-12T14:00:00Z,IN,1500.00,Client payment received"""

        result = await self.service._parse_csv_content(csv_content, "Wise")

        assert len(result["transactions"]) == 2
        assert result["period_start"] == "2025-01-10"
        assert result["period_end"] == "2025-01-12"

        assert result["transactions"][0]["direction"] == "OUT"
        assert result["transactions"][0]["amount"] == "250.00"

        assert result["transactions"][1]["direction"] == "IN"
        assert result["transactions"][1]["amount"] == "1500.00"

    @pytest.mark.asyncio
    async def test_parse_ocbc_csv(self):
        csv_content = b"""Transaction Date,Description,Debit,Credit
05/01/2025,SALARY CREDIT,,5000.00
06/01/2025,CREDIT CARD PAYMENT,1500.00,"""

        result = await self.service._parse_csv_content(csv_content, "OCBC")

        assert len(result["transactions"]) == 2
        assert result["transactions"][0]["direction"] == "IN"
        assert result["transactions"][1]["direction"] == "OUT"

    @pytest.mark.asyncio
    async def test_parse_generic_csv_with_amount_column(self):
        """[AC3.1.4] Parse Generic CSV format."""
        csv_content = b"""Date,Description,Amount
2025-01-01,Income,500.00
2025-01-02,Expense,-100.00"""

        result = await self.service._parse_csv_content(csv_content, "Unknown Bank")

        assert len(result["transactions"]) == 2
        assert result["transactions"][0]["direction"] == "IN"
        assert result["transactions"][0]["amount"] == "500.00"
        assert result["transactions"][1]["direction"] == "OUT"
        assert result["transactions"][1]["amount"] == "100.00"

    @pytest.mark.asyncio
    async def test_parse_empty_csv_raises_error(self):
        csv_content = b"""Transaction Date,Amount
"""
        with pytest.raises(ExtractionError, match="(No valid transactions|empty or has no data rows)"):
            await self.service._parse_csv_content(csv_content, "DBS")

    @pytest.mark.asyncio
    async def test_parse_csv_with_bom(self):
        """[AC3.1.5] Parse CSV with BOM marker."""
        csv_content = b"\xef\xbb\xbfTransaction Date,Debit Amount,Credit Amount,Description\n15 Jan 2025,,100.00,Test"

        result = await self.service._parse_csv_content(csv_content, "DBS")

        assert len(result["transactions"]) == 1
        assert result["transactions"][0]["amount"] == "100.00"

    @pytest.mark.asyncio
    async def test_parse_csv_various_date_formats(self):
        csv_content = b"""Date,Amount,Description
2025-01-15,100.00,ISO format
15/01/2025,200.00,DD/MM/YYYY format
01/15/2025,300.00,MM/DD/YYYY format"""

        result = await self.service._parse_csv_content(csv_content, "Generic")

        assert len(result["transactions"]) == 3

    @pytest.mark.asyncio
    async def test_parse_csv_with_currency_symbols(self):
        csv_content = b"""Date,Debit,Credit,Description
2025-01-15,$50.00,,Purchase
2025-01-16,,SGD 100.00,Deposit"""

        result = await self.service._parse_csv_content(csv_content, "Generic")

        assert len(result["transactions"]) == 2
        assert result["transactions"][0]["amount"] == "50.00"
        assert result["transactions"][1]["amount"] == "100.00"

    @pytest.mark.asyncio
    async def test_parse_csv_with_commas_in_amounts(self):
        csv_content = b"""Date,Credit,Description
2025-01-15,"1,500.00",Large deposit"""

        result = await self.service._parse_csv_content(csv_content, "Generic")

        assert len(result["transactions"]) == 1
        assert result["transactions"][0]["amount"] == "1500.00"

    @pytest.mark.asyncio
    async def test_parse_csv_skips_invalid_rows(self):
        csv_content = b"""Transaction Date,Debit Amount,Credit Amount,Description
15 Jan 2025,,100.00,Valid transaction
Invalid Date,,50.00,Should be skipped
16 Jan 2025,,200.00,Another valid one"""

        result = await self.service._parse_csv_content(csv_content, "DBS")

        assert len(result["transactions"]) == 2


# ---------------------------------------------------------------------------
# CSV edge cases for uncovered lines
# ---------------------------------------------------------------------------


class TestCSVEdgeCases:
    def setup_method(self):
        self.service = ExtractionService()

    # --- String input path (line 618) ---

    @pytest.mark.asyncio
    async def test_parse_csv_string_input(self):
        """CSV content as string (not bytes) triggers string path (line 618)."""
        csv_content = "\ufeffDate,Amount,Description\n2025-01-15,100.00,Test income"
        result = await self.service._parse_csv_content(csv_content, "Generic")
        assert len(result["transactions"]) == 1
        assert result["transactions"][0]["amount"] == "100.00"

    # --- PII detection warning (line 622) ---

    @pytest.mark.asyncio
    async def test_parse_csv_with_pii_warning(self):
        """CSV with PII-like content triggers warning (lines 621-627)."""
        # NRIC is a common PII type in Singapore
        csv_content = b"Date,Amount,Description\n2025-01-15,100.00,Payment to S1234567A"
        result = await self.service._parse_csv_content(csv_content, "Generic")
        assert len(result["transactions"]) == 1

    # --- parse_amount edge cases (lines 667-672) ---

    @pytest.mark.asyncio
    async def test_parse_amount_dash_only(self):
        """Amount column with just '-' should be skipped (line 667-668)."""
        csv_content = b"Transaction Date,Debit Amount,Credit Amount,Description\n15 Jan 2025,-,-,Dash amounts"
        with pytest.raises(ExtractionError, match="No valid transactions"):
            await self.service._parse_csv_content(csv_content, "DBS")

    @pytest.mark.asyncio
    async def test_parse_amount_invalid_decimal(self):
        """Amount column with invalid decimal triggers None return (lines 670-672)."""
        csv_content = b"Transaction Date,Debit Amount,Credit Amount,Description\n15 Jan 2025,abc,,Invalid amount"
        with pytest.raises(ExtractionError, match="No valid transactions"):
            await self.service._parse_csv_content(csv_content, "DBS")

    # --- DBS/POSB: no valid amount (lines 713-720) ---

    @pytest.mark.asyncio
    async def test_dbs_no_valid_amount_skipped(self):
        """DBS row with debit=None, credit=None -> skip (lines 712-720)."""
        csv_content = (
            b"Transaction Date,Debit Amount,Credit Amount,Transaction Ref1\n"
            b"15 Jan 2025,,,No amounts here\n"
            b"16 Jan 2025,,500.00,Valid deposit"
        )
        result = await self.service._parse_csv_content(csv_content, "DBS")
        assert len(result["transactions"]) == 1
        assert result["transactions"][0]["direction"] == "IN"

    # --- Wise: invalid date -> skip (lines 753-759) ---

    @pytest.mark.asyncio
    async def test_wise_invalid_date_skipped(self):
        """Wise row with invalid date -> skip (lines 752-759)."""
        csv_content = (
            b"ID,Created on,Direction,Source amount (after fees),Reference\n"
            b"123,INVALID_DATE,OUT,250.00,Bad date transfer\n"
            b"124,2025-01-12T14:00:00Z,IN,1500.00,Valid transfer"
        )
        result = await self.service._parse_csv_content(csv_content, "Wise")
        assert len(result["transactions"]) == 1
        assert result["transactions"][0]["direction"] == "IN"

    # --- Wise: invalid/zero amount -> skip (lines 763-769) ---

    @pytest.mark.asyncio
    async def test_wise_zero_amount_skipped(self):
        """Wise row with zero amount -> skip (lines 762-769)."""
        csv_content = (
            b"ID,Created on,Direction,Source amount (after fees),Reference\n"
            b"123,2025-01-10T10:30:00Z,OUT,0.00,Zero amount\n"
            b"124,2025-01-12T14:00:00Z,IN,1500.00,Valid transfer"
        )
        result = await self.service._parse_csv_content(csv_content, "Wise")
        assert len(result["transactions"]) == 1

    @pytest.mark.asyncio
    async def test_wise_invalid_amount_skipped(self):
        """Wise row with invalid amount -> skip (lines 762-769)."""
        csv_content = (
            b"ID,Created on,Direction,Source amount (after fees),Reference\n"
            b"123,2025-01-10T10:30:00Z,OUT,INVALID,Bad amount\n"
            b"124,2025-01-12T14:00:00Z,IN,1500.00,Valid transfer"
        )
        result = await self.service._parse_csv_content(csv_content, "Wise")
        assert len(result["transactions"]) == 1

    # --- OCBC: invalid date -> skip (lines 804-810) ---

    @pytest.mark.asyncio
    async def test_ocbc_invalid_date_skipped(self):
        """OCBC row with invalid date -> skip (lines 803-810)."""
        csv_content = (
            b"Transaction Date,Description,Debit,Credit\n"
            b"BAD_DATE,INVALID ROW,100.00,\n"
            b"05/01/2025,SALARY CREDIT,,5000.00"
        )
        result = await self.service._parse_csv_content(csv_content, "OCBC")
        assert len(result["transactions"]) == 1
        assert result["transactions"][0]["direction"] == "IN"

    # --- OCBC: no valid amount -> skip (lines 822-829) ---

    @pytest.mark.asyncio
    async def test_ocbc_no_valid_amount_skipped(self):
        """OCBC row with no valid amounts -> skip (lines 821-829)."""
        csv_content = (
            b"Transaction Date,Description,Debit,Credit\n"
            b"05/01/2025,NO AMOUNTS,,\n"
            b"06/01/2025,VALID,1500.00,"
        )
        result = await self.service._parse_csv_content(csv_content, "OCBC")
        assert len(result["transactions"]) == 1
        assert result["transactions"][0]["direction"] == "OUT"

    # --- Generic: invalid date -> skip (lines 858-864) ---

    @pytest.mark.asyncio
    async def test_generic_invalid_date_skipped(self):
        """Generic bank row with invalid date -> skip (lines 857-864)."""
        csv_content = (
            b"Date,Amount,Description\n"
            b"INVALID,100.00,Bad date row\n"
            b"2025-01-15,200.00,Valid row"
        )
        result = await self.service._parse_csv_content(csv_content, "Unknown Bank")
        assert len(result["transactions"]) == 1

    # --- Generic: invalid amount in single amount column -> skip (lines 872-878) ---

    @pytest.mark.asyncio
    async def test_generic_invalid_amount_column_skipped(self):
        """Generic bank row with invalid amount in amount column -> skip (lines 871-878)."""
        csv_content = (
            b"Date,Amount,Description\n"
            b"2025-01-15,INVALID_AMT,Bad amount\n"
            b"2025-01-16,200.00,Valid row"
        )
        result = await self.service._parse_csv_content(csv_content, "Unknown Bank")
        assert len(result["transactions"]) == 1
        assert result["transactions"][0]["amount"] == "200.00"

    # --- Generic: debit/credit fallback with no valid amount -> skip (lines 889-896) ---

    @pytest.mark.asyncio
    async def test_generic_debit_credit_no_valid_amount_skipped(self):
        """Generic bank row with debit/credit columns but no valid amounts -> skip (lines 888-896)."""
        csv_content = (
            b"Date,Debit,Credit,Description\n"
            b"2025-01-15,,,No amounts\n"
            b"2025-01-16,,500.00,Valid deposit"
        )
        result = await self.service._parse_csv_content(csv_content, "Unknown Bank")
        assert len(result["transactions"]) == 1
        assert result["transactions"][0]["direction"] == "IN"

    # --- Generic: no amount columns found -> skip (lines 897-903) ---

    @pytest.mark.asyncio
    async def test_generic_no_amount_columns_found(self):
        """Generic bank row with no amount columns at all -> skip (lines 897-903)."""
        csv_content = (
            b"Date,Description,Reference\n"
            b"2025-01-15,Some transaction,REF001"
        )
        with pytest.raises(ExtractionError, match="No valid transactions"):
            await self.service._parse_csv_content(csv_content, "Unknown Bank")

    # --- CSV parsing found no valid transactions (lines 922-928) ---

    @pytest.mark.asyncio
    async def test_csv_all_rows_skipped_raises_error(self):
        """All CSV rows skipped -> ExtractionError (lines 921-928)."""
        csv_content = (
            b"Transaction Date,Debit Amount,Credit Amount,Description\n"
            b"BAD DATE,,,Row 1 bad date\n"
            b"ALSO BAD,,,Row 2 bad date"
        )
        with pytest.raises(ExtractionError, match="No valid transactions found in CSV"):
            await self.service._parse_csv_content(csv_content, "DBS")
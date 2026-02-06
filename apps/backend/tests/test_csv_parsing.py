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

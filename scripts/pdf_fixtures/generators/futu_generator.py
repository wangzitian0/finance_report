"""Futu brokerage PDF generator."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from data.fake_data import generate_futu_transactions
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, Spacer, Table

from generators.base_generator import BasePDFGenerator


class FutuGenerator(BasePDFGenerator):
    """Generate a Futu brokerage statement PDF."""

    def generate(
        self,
        output_path: Path,
        period_start: datetime,
        period_end: datetime,
        account_last4: str = "6688",
    ):
        """Generate Futu statement PDF."""
        doc = self.create_document(output_path)
        elements = []
        styles = getSampleStyleSheet()

        font_family, font_size = self._get_font("header")
        header_style = ParagraphStyle(
            "Header",
            parent=styles["Heading1"],
            fontName=font_family,
            fontSize=font_size,
            spaceAfter=12,
        )
        elements.append(Paragraph("Futu Securities - Monthly Statement", header_style))

        period_str = period_end.strftime("%B %Y")
        elements.append(Paragraph(f"Statement Period: {period_str}", styles["Normal"]))
        elements.append(Spacer(1, 20))

        account_no = f"Account: ****{account_last4}"
        elements.append(Paragraph(account_no, styles["Normal"]))
        elements.append(Spacer(1, 20))

        opening_balance = Decimal("20000.00")
        txns, closing_balance = generate_futu_transactions(
            period_start,
            count=8,
            opening_balance=opening_balance,
        )

        if "account_summary" in self.template["tables"]:
            summary_config = self.template["tables"]["account_summary"]
            summary_data = [
                ["Account", "Opening Balance", "Closing Balance"],
                [
                    account_no,
                    f"SGD {opening_balance:,.2f}",
                    f"SGD {closing_balance:,.2f}",
                ],
            ]
            summary_table = Table(summary_data, colWidths=self._get_column_widths(summary_config))
            summary_table.setStyle(self._create_table_style(summary_config))
            elements.append(summary_table)
            elements.append(Spacer(1, 20))

        elements.append(Paragraph("Activity and Valuation", styles["Heading2"]))
        elements.append(Spacer(1, 10))

        table_config = self.template["tables"]["transaction_details"]
        columns = table_config["columns"]
        data = [[col["name"] for col in columns]]

        for txn in txns:
            data.append(
                [
                    txn["date"],
                    txn["type"],
                    txn["description"],
                    txn["amount"],
                    txn["currency"],
                ]
            )

        table = Table(data, colWidths=self._get_column_widths(table_config))
        table.setStyle(self._create_table_style(table_config))
        elements.append(table)

        doc.build(elements)
        print(f"✅ Generated Futu PDF: {output_path}")

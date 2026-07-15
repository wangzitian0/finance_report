"""Mari Bank PDF generator."""

from pathlib import Path
from datetime import datetime
from decimal import Decimal
from reportlab.platypus import Paragraph, Spacer, Table
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from ..data.fake_data import generate_mari_transactions
from .base_generator import BasePDFGenerator


class MariGenerator(BasePDFGenerator):
    """Generate Mari Bank statement PDF."""

    def generate(
        self,
        output_path: Path,
        period_start: datetime,
        period_end: datetime,
        account_last4: str = "1234",
    ):
        """Generate Mari Bank statement PDF."""
        doc = self.create_document(output_path)
        elements = []
        styles = getSampleStyleSheet()

        # Header
        font_family, font_size = self._get_font("header")
        header_style = ParagraphStyle(
            "Header",
            parent=styles["Heading1"],
            fontName=font_family,
            fontSize=font_size,
            spaceAfter=12,
        )
        elements.append(Paragraph("Mari Bank - E-Statement", header_style))

        # Statement Period
        period_str = f"STATEMENT PERIOD: {period_start.strftime('%d %b %Y').upper()} to {period_end.strftime('%d %b %Y').upper()}"
        elements.append(Paragraph(period_str, styles["Normal"]))
        elements.append(Spacer(1, 20))

        # Account Info
        account_no = f"****{account_last4}"
        elements.append(Paragraph(f"Account: {account_no}", styles["Normal"]))
        elements.append(Spacer(1, 20))

        # Generate transactions
        opening_balance = Decimal("3000.00")
        txns, closing_balance = generate_mari_transactions(
            period_start,
            count=12,
            opening_balance=opening_balance,
        )

        # Calculate totals
        total_outgoing = sum(abs(t["amount"]) for t in txns if t["outgoing"])
        total_incoming = sum(t["amount"] for t in txns if t["incoming"])

        # Account Summary Table
        if "account_summary" in self.template["tables"]:
            summary_config = self.template["tables"]["account_summary"]
            summary_data = [
                [
                    "Account",
                    "Opening Balance",
                    "Total Outgoing",
                    "Total Incoming",
                    "Ending Balance",
                ],
                [
                    account_no,
                    f"SGD {opening_balance:,.2f}",
                    f"SGD {total_outgoing:,.2f}",
                    f"SGD {total_incoming:,.2f}",
                    f"SGD {closing_balance:,.2f}",
                ],
            ]
            summary_table = Table(
                summary_data, colWidths=self._get_column_widths(summary_config)
            )
            summary_table.setStyle(self._create_table_style(summary_config))
            elements.append(summary_table)
            elements.append(Spacer(1, 20))

        interest_transactions = [
            txn for txn in txns if "interest" in str(txn["description"]).lower()
        ]
        if interest_transactions and "interest_details" in self.template["tables"]:
            elements.append(Paragraph("INTEREST DETAILS", styles["Heading2"]))
            elements.append(Spacer(1, 10))
            interest_config = self.template["tables"]["interest_details"]
            interest_data = [["Date", "Interest"]]
            for txn in interest_transactions:
                interest_data.append([txn["date"], txn["incoming"]])
            interest_table = Table(
                interest_data,
                colWidths=self._get_column_widths(interest_config),
            )
            interest_table.setStyle(self._create_table_style(interest_config))
            elements.append(interest_table)
            elements.append(Spacer(1, 20))

        # Transaction Details
        elements.append(Paragraph("TRANSACTION DETAILS", styles["Heading2"]))
        elements.append(Spacer(1, 10))

        table_config = self.template["tables"]["transaction_details"]
        columns = table_config["columns"]

        # Table header
        header_row = [col["name"] for col in columns]
        data = [header_row]

        # Transaction rows
        for txn in txns:
            row = [
                txn["date"],
                txn["description"],
                txn["outgoing"],
                txn["incoming"],
            ]
            data.append(row)

        # Create table
        col_widths = self._get_column_widths(table_config)
        table = Table(data, colWidths=col_widths)
        table.setStyle(self._create_table_style(table_config))
        elements.append(table)

        # Build PDF
        doc.build(elements)
        print(f"✅ Generated Mari Bank PDF: {output_path}")

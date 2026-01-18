"""Moomoo SG Brokerage PDF generator."""
from pathlib import Path
from datetime import datetime
from decimal import Decimal
from reportlab.platypus import Paragraph, Spacer, Table
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from generators.base_generator import BasePDFGenerator
from data.fake_data import generate_moomoo_transactions


class MoomooGenerator(BasePDFGenerator):
    """Generate Moomoo brokerage statement PDF."""
    
    def generate(
        self,
        output_path: Path,
        period_start: datetime,
        period_end: datetime,
        account_last4: str = "1582",
    ):
        """Generate Moomoo statement PDF."""
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
        elements.append(Paragraph("Moomoo SG - Monthly Statement", header_style))
        
        # Statement Period
        period_str = period_end.strftime("%B %Y")
        elements.append(Paragraph(f"Statement Period: {period_str}", styles["Normal"]))
        elements.append(Spacer(1, 20))
        
        # Account Info
        account_no = f"Account: ****{account_last4}"
        elements.append(Paragraph(account_no, styles["Normal"]))
        elements.append(Spacer(1, 20))
        
        # Generate transactions
        opening_balance = Decimal("10000.00")
        txns, closing_balance = generate_moomoo_transactions(
            period_start,
            count=10,
            opening_balance=opening_balance,
        )
        
        # Account Summary
        if "account_summary" in self.template["tables"]:
            summary_config = self.template["tables"]["account_summary"]
            summary_data = [
                ["Account", "Opening Balance", "Closing Balance"],
                [
                    account_no,
                    f"USD {opening_balance:,.2f}",
                    f"USD {closing_balance:,.2f}",
                ],
            ]
            summary_table = Table(summary_data, colWidths=self._get_column_widths(summary_config))
            summary_table.setStyle(self._create_table_style(summary_config))
            elements.append(summary_table)
            elements.append(Spacer(1, 20))
        
        # Transaction Details
        elements.append(Paragraph("Transaction Details", styles["Heading2"]))
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
                txn["type"],
                txn["description"],
                txn["amount"],
                txn["currency"],
            ]
            data.append(row)
        
        # Create table
        col_widths = self._get_column_widths(table_config)
        table = Table(data, colWidths=col_widths)
        table.setStyle(self._create_table_style(table_config))
        elements.append(table)
        
        # Build PDF
        doc.build(elements)
        print(f"✅ Generated Moomoo PDF: {output_path}")

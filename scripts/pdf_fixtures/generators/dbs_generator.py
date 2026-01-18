"""DBS Bank PDF generator."""
from pathlib import Path
from datetime import datetime
from decimal import Decimal
from reportlab.lib import colors
from reportlab.platypus import Paragraph, Spacer, Table
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from generators.base_generator import BasePDFGenerator
from data.fake_data import generate_dbs_transactions


class DBSGenerator(BasePDFGenerator):
    """Generate DBS Bank statement PDF."""
    
    def generate(
        self,
        output_path: Path,
        period_start: datetime,
        period_end: datetime,
        account_last4: str = "5678",
    ):
        """Generate DBS statement PDF."""
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
        elements.append(Paragraph("DBS Bank - E-Statement", header_style))
        
        # Statement Period
        period_str = f"{period_start.strftime('%d %b %Y')} to {period_end.strftime('%d %b %Y')}"
        elements.append(Paragraph(f"Statement Period: {period_str}", styles["Normal"]))
        elements.append(Spacer(1, 20))
        
        # Account Info
        account_no = f"***-****-{account_last4}"
        elements.append(Paragraph(f"Account No: {account_no}", styles["Normal"]))
        elements.append(Spacer(1, 20))
        
        # Generate transactions
        opening_balance = Decimal("5000.00")
        txns, closing_balance = generate_dbs_transactions(
            period_start,
            count=15,
            opening_balance=opening_balance,
        )
        
        # Opening Balance
        elements.append(Paragraph(f"Opening Balance: SGD {opening_balance:,.2f}", styles["Normal"]))
        elements.append(Spacer(1, 10))
        
        # Transaction Details Table
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
                txn["withdrawal"],
                txn["deposit"],
                txn["balance"],
            ]
            data.append(row)
        
        # Create table
        col_widths = self._get_column_widths(table_config)
        table = Table(data, colWidths=col_widths)
        table.setStyle(self._create_table_style(table_config))
        elements.append(table)
        
        elements.append(Spacer(1, 20))
        
        # Closing Balance
        elements.append(Paragraph(f"Closing Balance: SGD {closing_balance:,.2f}", styles["Normal"]))
        
        # Build PDF
        doc.build(elements)
        print(f"✅ Generated DBS PDF: {output_path}")

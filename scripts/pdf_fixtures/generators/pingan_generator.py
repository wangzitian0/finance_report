"""Pingan (平安银行) PDF generator."""
from pathlib import Path
from datetime import datetime
from decimal import Decimal
from reportlab.platypus import Paragraph, Spacer, Table
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from generators.base_generator import BasePDFGenerator
from generators.font_utils import register_chinese_fonts, get_safe_font
from data.fake_data import generate_pingan_transactions


class PinganGenerator(BasePDFGenerator):
    """Generate Pingan Bank statement PDF."""
    
    def __init__(self, template_path: Path):
        super().__init__(template_path)
        self.chinese_font = register_chinese_fonts()
    
    def generate(
        self,
        output_path: Path,
        period_start: datetime,
        period_end: datetime,
        account_last4: str = "1234",
    ):
        """Generate Pingan statement PDF."""
        doc = self.create_document(output_path)
        elements = []
        styles = getSampleStyleSheet()
        
        # Header - Force Chinese font if available
        font_family, font_size = self._get_font("header")
        header_font = self.chinese_font if self.chinese_font else get_safe_font(font_family, self.chinese_font)
        
        header_style = ParagraphStyle(
            "Header",
            parent=styles["Heading1"],
            fontName=header_font,
            fontSize=font_size,
            spaceAfter=12,
        )
        # Always use Chinese header
        elements.append(Paragraph("平安银行交易流水", header_style))
        
        # Account Info - Force Chinese font if available
        account_no = f"6221 **** **** {account_last4}"
        body_font = self.chinese_font if self.chinese_font else get_safe_font(self._get_font("body")[0], self.chinese_font)
        body_style = ParagraphStyle(
            "Body",
            parent=styles["Normal"],
            fontName=body_font,
        )
        elements.append(Paragraph(f"账户: {account_no}", body_style))
        
        # Period
        period_str = f"{period_start.strftime('%Y-%m-%d')} 至 {period_end.strftime('%Y-%m-%d')}"
        elements.append(Paragraph(f"账期: {period_str}", body_style))
        elements.append(Spacer(1, 20))
        
        # Generate transactions
        opening_balance = Decimal("8000.00")
        txns, closing_balance = generate_pingan_transactions(
            period_start,
            count=15,
            opening_balance=opening_balance,
        )
        
        # Opening Balance
        elements.append(Paragraph(f"期初余额: CNY {opening_balance:,.2f}", body_style))
        elements.append(Spacer(1, 10))
        
        # Transaction Table
        table_config = self.template["tables"]["transaction_details"]
        columns = table_config["columns"]
        
        # Table header - Force Chinese font if available
        table_font = self.chinese_font if self.chinese_font else get_safe_font(self._get_font("table_header")[0], self.chinese_font)
        header_row = [col["name"] for col in columns]
        data = [header_row]
        
        # Transaction rows
        # Force Chinese font for table body
        table_body_font = self.chinese_font if self.chinese_font else get_safe_font(self._get_font("table_body")[0], self.chinese_font)
        
        for txn in txns:
            row = [
                txn["date"],
                txn["type"],
                txn["amount"],
                txn["balance"],
                txn["description"],
            ]
            data.append(row)
        
        # Create table with Chinese font
        col_widths = self._get_column_widths(table_config)
        table = Table(data, colWidths=col_widths)
        table_style = self._create_table_style(table_config, table_font=table_font)
        # Force Chinese font for all table cells (header and body)
        table_style.add("FONTNAME", (0, 0), (-1, -1), table_body_font)  # Apply to all rows including header
        table.setStyle(table_style)
        elements.append(table)
        
        elements.append(Spacer(1, 20))
        
        # Closing Balance
        elements.append(Paragraph(f"期末余额: CNY {closing_balance:,.2f}", body_style))
        
        # Build PDF
        doc.build(elements)
        print(f"✅ Generated Pingan PDF: {output_path}")

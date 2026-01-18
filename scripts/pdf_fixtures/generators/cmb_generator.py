"""CMB (China Merchants Bank) PDF generator."""
from pathlib import Path
from datetime import datetime
from decimal import Decimal
from reportlab.platypus import Paragraph, Spacer, Table
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from generators.base_generator import BasePDFGenerator
from generators.font_utils import register_chinese_fonts, get_safe_font, can_display_chinese
from data.fake_data import generate_cmb_transactions


class CMBGenerator(BasePDFGenerator):
    """Generate CMB Bank statement PDF."""
    
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
        """Generate CMB statement PDF."""
        doc = self.create_document(output_path)
        elements = []
        styles = getSampleStyleSheet()
        
        # Header
        font_family, font_size = self._get_font("header")
        safe_font = get_safe_font(font_family, self.chinese_font)
        
        header_style = ParagraphStyle(
            "Header",
            parent=styles["Heading1"],
            fontName=safe_font,
            fontSize=font_size,
            spaceAfter=12,
        )
        # Always use Chinese header (font should be registered)
        elements.append(Paragraph("招商银行交易流水", header_style))
        
        # Account Info - Set font for body text
        account_no = f"6214 **** **** {account_last4}"
        body_font = get_safe_font(self._get_font("body")[0], self.chinese_font)
        body_style = ParagraphStyle(
            "Body",
            parent=styles["Normal"],
            fontName=body_font,
        )
        # Always use Chinese (font should be registered)
        elements.append(Paragraph(f"账户: {account_no}", body_style))
        
        # Period
        period_str = f"{period_start.strftime('%Y-%m-%d')} 至 {period_end.strftime('%Y-%m-%d')}"
        elements.append(Paragraph(f"账期: {period_str}", body_style))
        elements.append(Spacer(1, 20))
        
        # Generate transactions
        opening_balance = Decimal("10000.00")
        txns, closing_balance = generate_cmb_transactions(
            period_start,
            count=20,
            opening_balance=opening_balance,
        )
        
        # Opening Balance
        elements.append(Paragraph(f"期初余额: CNY {opening_balance:,.2f}", body_style))
        elements.append(Spacer(1, 10))
        
        # Transaction Table
        table_config = self.template["tables"]["transaction_details"]
        columns = table_config["columns"]
        
        # Table header - Always use Chinese
        table_font = get_safe_font(self._get_font("table_header")[0], self.chinese_font)
        header_row = [col["name"] for col in columns]
        data = [header_row]
        
        # Transaction rows
        for txn in txns:
            row = [
                txn["date"],
                txn["currency"],
                txn["amount"],
                txn["balance"],
                txn["description"],
                txn["counterparty"],
            ]
            data.append(row)
        
        # Create table with Chinese font
        col_widths = self._get_column_widths(table_config)
        table = Table(data, colWidths=col_widths)
        table_style = self._create_table_style(table_config, table_font=table_font)
        # Set Chinese font for table body rows
        table_body_font = get_safe_font(self._get_font("table_body")[0], self.chinese_font)
        table_style.add("FONTNAME", (0, 1), (-1, -1), table_body_font)
        table.setStyle(table_style)
        elements.append(table)
        
        elements.append(Spacer(1, 20))
        
        # Closing Balance
        elements.append(Paragraph(f"期末余额: CNY {closing_balance:,.2f}", body_style))
        
        # Build PDF
        doc.build(elements)
        print(f"✅ Generated CMB PDF: {output_path}")

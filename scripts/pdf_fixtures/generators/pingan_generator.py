"""Pingan (平安银行) PDF generator."""
from pathlib import Path
from datetime import datetime
from decimal import Decimal
from reportlab.lib import colors
from reportlab.platypus import Paragraph, Spacer, Table
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from generators.base_generator import BasePDFGenerator
from data.fake_data import generate_pingan_transactions


class PinganGenerator(BasePDFGenerator):
    """Generate Pingan Bank statement PDF."""
    
    def __init__(self, template_path: Path):
        super().__init__(template_path)
        self.chinese_font = None
        self._register_chinese_fonts()
    
    def _register_chinese_fonts(self):
        """Register Chinese fonts if available."""
        # Try to register Chinese fonts from system
        from pathlib import Path
        font_paths = [
            "/System/Library/Fonts/Supplemental/STHeiti Light.ttc",  # macOS
            "/System/Library/Fonts/STHeiti Light.ttc",  # macOS
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",  # Linux
        ]
        
        for font_path in font_paths:
            if Path(font_path).exists():
                try:
                    pdfmetrics.registerFont(TTFont("ChineseFont", font_path))
                    self.chinese_font = "ChineseFont"
                    return
                except Exception:
                    continue
        
        self.chinese_font = None
    
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
        
        # Header - Use English to avoid font issues
        font_family, font_size = self._get_font("header")
        if self.chinese_font:
            font_family = self.chinese_font
        elif font_family not in ["Helvetica", "Helvetica-Bold", "Times-Roman", "Courier"]:
            font_family = "Helvetica-Bold"
        
        header_style = ParagraphStyle(
            "Header",
            parent=styles["Heading1"],
            fontName=font_family,
            fontSize=font_size,
            spaceAfter=12,
        )
        elements.append(Paragraph("Pingan Bank - Transaction Statement", header_style))
        
        # Account Info
        account_no = f"6221 **** **** {account_last4}"
        elements.append(Paragraph(f"Account: {account_no}", styles["Normal"]))
        
        # Period
        period_str = f"{period_start.strftime('%Y-%m-%d')} to {period_end.strftime('%Y-%m-%d')}"
        elements.append(Paragraph(f"Period: {period_str}", styles["Normal"]))
        elements.append(Spacer(1, 20))
        
        # Generate transactions
        opening_balance = Decimal("8000.00")
        txns, closing_balance = generate_pingan_transactions(
            period_start,
            count=15,
            opening_balance=opening_balance,
        )
        
        # Opening Balance
        elements.append(Paragraph(f"Opening Balance: CNY {opening_balance:,.2f}", styles["Normal"]))
        elements.append(Spacer(1, 10))
        
        # Transaction Table
        table_config = self.template["tables"]["transaction_details"]
        columns = table_config["columns"]
        
        # Table header - Use English column names to avoid font issues
        column_name_map = {
            "交易日期": "Date",
            "交易类型": "Type",
            "交易金额": "Amount",
            "余额": "Balance",
            "交易摘要": "Description",
        }
        header_row = [column_name_map.get(col["name"], col["name"]) for col in columns]
        data = [header_row]
        
        # Transaction rows
        for txn in txns:
            row = [
                txn["date"],
                txn["type"],
                txn["amount"],
                txn["balance"],
                txn["description"],
            ]
            data.append(row)
        
        # Create table
        col_widths = self._get_column_widths(table_config)
        table = Table(data, colWidths=col_widths)
        table.setStyle(self._create_table_style(table_config))
        elements.append(table)
        
        elements.append(Spacer(1, 20))
        
        # Closing Balance
        elements.append(Paragraph(f"Closing Balance: CNY {closing_balance:,.2f}", styles["Normal"]))
        
        # Build PDF
        doc.build(elements)
        print(f"✅ Generated Pingan PDF: {output_path}")

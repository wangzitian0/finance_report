#!/usr/bin/env python
"""
Generate synthetic PDF bank statements for E2E testing.
Usage: python scripts/generate_pdf_fixtures.py [output_dir]

Requires: reportlab
"""

import sys
import random
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal

# Add repo/ to sys.path if running from root to ensure potential future imports
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root / "repo"))

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
except ImportError:
    print("❌ reportlab not installed. Please run 'cd repo && uv sync' or 'pip install reportlab'.")
    sys.exit(1)

def generate_transactions(start_date: datetime, count: int = 10):
    """Generate a list of synthetic transactions."""
    descriptions = [
        ("GRAB RIDE", -15.00, -30.00),
        ("STARBUCKS COFFEE", -5.00, -10.00),
        ("NETFLIX SUBSCRIPTION", -15.90, -15.90),
        ("SALARY", 3000.00, 5000.00),
        ("NTUC FAIRPRICE", -50.00, -150.00),
        ("SPOTIFY", -9.90, -9.90),
        ("RESTAURANT PAYMENT", -40.00, -120.00),
        ("TRANSFER FROM FRIEND", 10.00, 50.00),
    ]
    
    txns = []
    balance = Decimal("1000.00")
    
    current_date = start_date
    for _ in range(count):
        # Advance date by 0-2 days
        current_date += timedelta(days=random.randint(0, 2))
        
        desc, min_amt, max_amt = random.choice(descriptions)
        
        if min_amt == max_amt:
            amount = Decimal(str(min_amt))
        else:
            amount = Decimal(str(round(random.uniform(min_amt, max_amt), 2)))
            
        balance += amount
        
        txns.append({
            "date": current_date.strftime("%d %b %Y"),
            "description": desc,
            "withdrawal": f"{abs(amount):.2f}" if amount < 0 else "",
            "deposit": f"{amount:.2f}" if amount > 0 else "",
            "balance": f"{balance:.2f}"
        })
        
    return txns

def create_statement_pdf(filepath: Path, institution: str, period: str):
    """Create a PDF file mimicking a bank statement."""
    doc = SimpleDocTemplate(str(filepath), pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()
    
    # Header
    header_style = ParagraphStyle(
        'Header',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=12
    )
    elements.append(Paragraph(f"{institution} - E-Statement", header_style))
    elements.append(Paragraph(f"Statement Period: {period}", styles['Normal']))
    elements.append(Spacer(1, 20))
    
    # Account Info
    elements.append(Paragraph("Account Name: E2E TEST USER", styles['Normal']))
    elements.append(Paragraph("Account No: 123-456-789", styles['Normal']))
    elements.append(Spacer(1, 20))
    
    # Transactions Table
    txns = generate_transactions(datetime.now() - timedelta(days=30), count=15)
    
    data = [['Date', 'Transaction Description', 'Withdrawal', 'Deposit', 'Balance']]
    for t in txns:
        data.append([t['date'], t['description'], t['withdrawal'], t['deposit'], t['balance']])
        
    # Table Styling
    t = Table(data, colWidths=[70, 200, 60, 60, 70])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (1, 1), (1, -1), 'LEFT'),  # Left align descriptions
        ('ALIGN', (2, 1), (-1, -1), 'RIGHT'), # Right align numbers
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    
    elements.append(t)
    
    # Build
    doc.build(elements)
    print(f"✅ Generated: {filepath}")

def main():
    parser = argparse.ArgumentParser(description="Generate E2E PDF Fixtures")
    parser.add_argument("output_dir", nargs="?", default="tmp/fixtures", help="Directory to save PDFs")
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate 1 DBS-style and 1 Citi-style
    create_statement_pdf(output_dir / "e2e_dbs_statement.pdf", "DBS Bank", "Jan 2026")
    create_statement_pdf(output_dir / "e2e_citi_statement.pdf", "Citi Bank", "Jan 2026")

if __name__ == "__main__":
    main()

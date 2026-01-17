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

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
except ImportError:
    print("❌ reportlab not installed. Please run 'uv sync' from the repository root or 'pip install reportlab'.")
    sys.exit(1)

<<<<<<< HEAD
def generate_transactions(start_date: datetime, count: int = 10) -> list[dict]:
    """Generate a list of synthetic transactions."""
    descriptions = [
        ("GRAB RIDE", -15, -30),
# ... (middle content same) ...
    return txns

def create_statement_pdf(filepath: Path, institution: str, period: str) -> None:
    """Create a PDF file mimicking a bank statement."""
    doc = SimpleDocTemplate(str(filepath), pagesize=A4)
# ... (middle content same) ...
    doc.build(elements)
    print(f"✅ Generated: {filepath}")

def main() -> None:
=======
def generate_transactions(start_date: datetime, count: int = 10):
    """Generate a list of synthetic transactions."""
    descriptions = [
        ("GRAB RIDE", -15, -30),
        ("STARBUCKS COFFEE", -5, -10),
        ("NETFLIX SUBSCRIPTION", -15.90, -15.90),
        ("SALARY", 3000, 5000),
        ("NTUC FAIRPRICE", -50, -150),
        ("SPOTIFY", -9.90, -9.90),
        ("RESTAURANT PAYMENT", -40, -120),
        ("TRANSFER FROM FRIEND", 10, 50),
    ]
    
    txns = []
    balance = Decimal("1000.00")
    
    current_date = start_date
    for _ in range(count):
        # Advance date by 0-2 days
        current_date += timedelta(days=random.randint(0, 2))
        
        desc, min_amt, max_amt = random.choice(descriptions)
        
        # Generate random amount as Decimal
        if min_amt == max_amt:
            amount = Decimal(str(min_amt))
        else:
            # Random decimal between min and max (inclusive-ish)
            # Convert to cents, rand int, convert back
            min_cents = int(min_amt * 100)
            max_cents = int(max_amt * 100)
            cents = random.randint(min_cents, max_cents)
            amount = Decimal(cents) / Decimal(100)
            
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
>>>>>>> origin/main
    parser = argparse.ArgumentParser(description="Generate E2E PDF Fixtures")
    parser.add_argument("output_dir", nargs="?", default="tmp/fixtures", help="Directory to save PDFs")
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
<<<<<<< HEAD
    # Derive statement period from the last 30 days
    now = datetime.now()
    start_date = now - timedelta(days=30)
    period_str = f"{start_date.strftime('%d %b %Y')} - {now.strftime('%d %b %Y')}"
    
    # Generate 1 DBS-style and 1 Citi-style
    create_statement_pdf(output_dir / "e2e_dbs_statement.pdf", "DBS Bank", period_str)
    create_statement_pdf(output_dir / "e2e_citi_statement.pdf", "Citi Bank", period_str)
=======
    # Generate 1 DBS-style and 1 Citi-style
    create_statement_pdf(output_dir / "e2e_dbs_statement.pdf", "DBS Bank", "Jan 2026")
    create_statement_pdf(output_dir / "e2e_citi_statement.pdf", "Citi Bank", "Jan 2026")
>>>>>>> origin/main

if __name__ == "__main__":
    main()

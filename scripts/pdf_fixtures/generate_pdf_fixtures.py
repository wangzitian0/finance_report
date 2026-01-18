#!/usr/bin/env python
"""
Generate synthetic PDF bank statements for E2E testing.

Usage:
    # From pdf_fixtures directory:
    # Generate all sources
    python generate_pdf_fixtures.py --source all
    
    # Generate specific source
    python generate_pdf_fixtures.py --source dbs
    
    # Custom output directory
    python generate_pdf_fixtures.py --source dbs --output /path/to/output/
    
    # Backward compatibility (generates e2e_dbs_statement.pdf)
    python generate_pdf_fixtures.py [output_dir]

Requires: reportlab, pyyaml
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
except ImportError:
    print("❌ reportlab not installed. Please run 'uv sync' from the repository root or 'pip install reportlab'.")
    sys.exit(1)




def generate_legacy_dbs_pdf(output_path: Path):
    """Generate legacy DBS PDF for backward compatibility with existing E2E tests."""
    from decimal import Decimal
    import random
    
    def generate_transactions(start_date: datetime, count: int = 15):
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
            current_date += timedelta(days=random.randint(0, 2))
            desc, min_amt, max_amt = random.choice(descriptions)
            
            if min_amt == max_amt:
                amount = Decimal(str(min_amt))
            else:
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
    
    # Generate period
    now = datetime.now()
    start_date = now - timedelta(days=30)
    period_str = f"{start_date.strftime('%d %b %Y')} - {now.strftime('%d %b %Y')}"
    
    # Create PDF
    doc = SimpleDocTemplate(str(output_path), pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()
    
    # Header
    header_style = ParagraphStyle(
        'Header',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=12
    )
    elements.append(Paragraph("DBS Bank - E-Statement", header_style))
    elements.append(Paragraph(f"Statement Period: {period_str}", styles['Normal']))
    elements.append(Spacer(1, 20))
    
    # Account Info
    elements.append(Paragraph("Account Name: E2E TEST USER", styles['Normal']))
    elements.append(Paragraph("Account No: 123-456-789", styles['Normal']))
    elements.append(Spacer(1, 20))
    
    # Transactions Table
    txns = generate_transactions(start_date, count=15)
    data = [['Date', 'Transaction Description', 'Withdrawal', 'Deposit', 'Balance']]
    for t in txns:
        data.append([t['date'], t['description'], t['withdrawal'], t['deposit'], t['balance']])
    
    # Table Styling
    t = Table(data, colWidths=[70, 200, 60, 60, 70])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (1, 1), (1, -1), 'LEFT'),
        ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    
    elements.append(t)
    doc.build(elements)
    print(f"✅ Generated: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate E2E PDF Fixtures")
    parser.add_argument(
        "--source",
        choices=["dbs", "cmb", "mari", "moomoo", "pingan", "all"],
        default=None,
        help="Source to generate (dbs, cmb, mari, moomoo, pingan, all). If not specified, uses legacy mode.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Directory to save PDFs (default: pdf_fixtures/output/)",
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        help="[Legacy] Directory to save PDFs (for backward compatibility)",
    )
    
    args = parser.parse_args()
    
    # Handle legacy mode (backward compatibility)
    if args.source is None:
        output_dir = Path(args.output_dir) if args.output_dir else args.output
        if output_dir is None:
            # Default to tmp/fixtures for legacy mode
            output_dir = Path("tmp/fixtures")
        output_dir.mkdir(parents=True, exist_ok=True)
        generate_legacy_dbs_pdf(output_dir / "e2e_dbs_statement.pdf")
        return
    
    # New mode: use generators
    output_dir = args.output
    if output_dir is None:
        # Default to pdf_fixtures/output/
        output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Import generators
    try:
        from generators.dbs_generator import DBSGenerator
        from generators.cmb_generator import CMBGenerator
        from generators.mari_generator import MariGenerator
        from generators.moomoo_generator import MoomooGenerator
        from generators.pingan_generator import PinganGenerator
    except ImportError as e:
        print(f"❌ Error importing generators: {e}")
        print("Make sure you're running from the pdf_fixtures directory.")
        sys.exit(1)
    
    # Template paths
    templates_dir = Path(__file__).parent / "templates"
    
    # Generate period (last 30 days)
    now = datetime.now()
    period_start = now - timedelta(days=30)
    period_end = now
    
    # Period string for filename (e.g., "2501" for Jan 2025)
    period_str = period_end.strftime("%y%m")
    
    sources_to_generate = []
    if args.source == "all":
        sources_to_generate = ["dbs", "cmb", "mari", "moomoo", "pingan"]
    else:
        sources_to_generate = [args.source]
    
    for source in sources_to_generate:
        # Create source subdirectory
        source_dir = output_dir / source
        source_dir.mkdir(parents=True, exist_ok=True)
        
        template_path = templates_dir / f"{source}_template.yaml"
        output_path = source_dir / f"test_{source}_{period_str}.pdf"
        
        try:
            if source == "dbs":
                generator = DBSGenerator(template_path)
                generator.generate(output_path, period_start, period_end)
            elif source == "cmb":
                generator = CMBGenerator(template_path)
                generator.generate(output_path, period_start, period_end)
            elif source == "mari":
                generator = MariGenerator(template_path)
                generator.generate(output_path, period_start, period_end)
            elif source == "moomoo":
                generator = MoomooGenerator(template_path)
                generator.generate(output_path, period_start, period_end)
            elif source == "pingan":
                generator = PinganGenerator(template_path)
                generator.generate(output_path, period_start, period_end)
        except Exception as e:
            print(f"❌ Error generating {source} PDF: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    
    print(f"\n✅ Generated PDFs in: {output_dir}")


if __name__ == "__main__":
    main()

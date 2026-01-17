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
    parser = argparse.ArgumentParser(description="Generate E2E PDF Fixtures")
    parser.add_argument("output_dir", nargs="?", default="tmp/fixtures", help="Directory to save PDFs")
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Derive statement period from the last 30 days
    now = datetime.now()
    start_date = now - timedelta(days=30)
    period_str = f"{start_date.strftime('%d %b %Y')} - {now.strftime('%d %b %Y')}"
    
    # Generate 1 DBS-style and 1 Citi-style
    create_statement_pdf(output_dir / "e2e_dbs_statement.pdf", "DBS Bank", period_str)
    create_statement_pdf(output_dir / "e2e_citi_statement.pdf", "Citi Bank", period_str)

if __name__ == "__main__":
    main()

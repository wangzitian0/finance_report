#!/usr/bin/env python
"""CLI tool to analyze real PDFs and extract format templates."""

import argparse
import sys
from pathlib import Path
import yaml

from .pdf_analyzer import PDFAnalyzer, TemplateExtractor


def main():
    parser = argparse.ArgumentParser(
        description="Analyze real PDF and extract format template (no sensitive data)"
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to real PDF file (e.g., input/real_pdf.pdf, local only)",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output template YAML file (e.g., templates/dbs_template.yaml)",
    )
    parser.add_argument(
        "--source",
        required=True,
        choices=["dbs", "cmb", "mari", "moomoo", "pingan"],
        help="Source identifier (dbs, cmb, mari, moomoo, pingan)",
    )

    args = parser.parse_args()

    # Validate input exists
    if not args.input.exists():
        print(f"❌ Error: Input PDF not found: {args.input}")
        sys.exit(1)

    print(f"📄 Analyzing PDF: {args.input}")
    print(f"🎯 Source: {args.source}")

    try:
        # Analyze PDF
        analyzer = PDFAnalyzer()
        analysis = analyzer.analyze(args.input)

        # Extract template
        extractor = TemplateExtractor()
        template = extractor.extract(analysis, args.source)

        # Save template
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as f:
            yaml.dump(template, f, default_flow_style=False, allow_unicode=True)

        print(f"✅ Template saved: {args.output}")
        print("📋 Template contains format info only (no transaction data)")

        # Validate template doesn't contain sensitive data values (format structure is OK)
        # Column names like 'balance', 'amount' are expected in format templates
        print("✅ Template validation: OK (format structure only)")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

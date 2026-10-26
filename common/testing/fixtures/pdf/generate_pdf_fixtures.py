#!/usr/bin/env python
"""
Generate synthetic PDF bank statements for E2E testing.

Usage:
    # Generate all sources
    python tools/generate_pdf_fixtures.py --source all

    # Generate specific source
    python tools/generate_pdf_fixtures.py --source dbs

    # Custom output directory
    python tools/generate_pdf_fixtures.py --source dbs --output /path/to/output/

Requires: reportlab, pyyaml
"""

import argparse
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate E2E PDF Fixtures")
    parser.add_argument(
        "--source",
        choices=["dbs", "cmb", "mari", "moomoo", "futu", "pingan", "all"],
        required=True,
        help="Source to generate (dbs, cmb, mari, moomoo, futu, pingan, all).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Directory to save PDFs (default: pdf_fixtures/output/)",
    )
    parser.add_argument(
        "--period-end",
        type=date.fromisoformat,
        default=None,
        help=(
            "Statement period end date (YYYY-MM-DD). Default: now. "
            "The period starts 30 days earlier and the file name uses this month."
        ),
    )

    args = parser.parse_args(argv)

    output_dir = args.output
    if output_dir is None:
        # Default to pdf_fixtures/output/
        output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Import generators
    try:
        from .generators.cmb_generator import CMBGenerator
        from .generators.dbs_generator import DBSGenerator
        from .generators.futu_generator import FutuGenerator
        from .generators.mari_generator import MariGenerator
        from .generators.moomoo_generator import MoomooGenerator
        from .generators.pingan_generator import PinganGenerator
    except ImportError as e:
        print(f"❌ Error importing generators: {e}")
        print(
            "Make sure common.testing.fixtures.pdf is importable from the repository root."
        )
        return 1

    # Template paths
    templates_dir = Path(__file__).parent / "templates"

    # Generate period: 30 days ending now, or ending on --period-end
    period_end = (
        datetime.combine(args.period_end, time(12, 0), tzinfo=UTC)
        if args.period_end is not None
        else datetime.now(UTC)
    )
    period_start = period_end - timedelta(days=30)

    # Period string for filename (e.g., "2501" for Jan 2025)
    period_str = period_end.strftime("%y%m")

    sources_to_generate = []
    if args.source == "all":
        sources_to_generate = ["dbs", "cmb", "mari", "moomoo", "futu", "pingan"]
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
            elif source == "futu":
                generator = FutuGenerator(template_path)
                generator.generate(output_path, period_start, period_end)
            elif source == "pingan":
                generator = PinganGenerator(template_path)
                generator.generate(output_path, period_start, period_end)
        except Exception as e:
            print(f"❌ Error generating {source} PDF: {e}")
            import traceback

            traceback.print_exc()
            return 1

    print(f"\n✅ Generated PDFs in: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

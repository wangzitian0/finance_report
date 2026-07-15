"""Shared PDF-fixture path resolution for provider-backed E2E journeys.

Single owner for locating (or generating at runtime) the synthetic statement
PDFs the staging ``-m llm`` gates upload. The generators and their output
directory live in the ``testing`` package
(``common/testing/fixtures/pdf/output/<source>/``) since the #1541/#1567
fixture migration; the previous per-test copies of this logic still globbed
the retired ``tools/_lib/pdf_fixtures/output`` path, so every
runtime-generation fallback silently produced files the glob never saw and
the journey SKIPPED — the canary proved nothing.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DIR = REPO_ROOT / "common" / "testing" / "fixtures" / "pdf" / "generated"
OUTPUT_DIR = REPO_ROOT / "common" / "testing" / "fixtures" / "pdf" / "output"
GENERATE_SCRIPT = REPO_ROOT / "tools" / "generate_pdf_fixtures.py"


def committed_fixture_pdf(name: str) -> Path:
    """A committed PDF + expected-JSON pair from the generated/ directory."""
    path = GENERATED_DIR / name
    assert path.exists(), f"committed fixture missing: {path}"
    return path


def generated_pdf_path(source: str) -> Path:
    """Locate a runtime-generated statement PDF for ``source``, generating it
    via ``tools/generate_pdf_fixtures.py`` when absent.

    Search order:
      1. ``output/<source>/test_<source>_<yymm>.pdf`` — current-month build
      2. ``output/<source>/test_<source>_*.pdf``      — any prior build
      3. on-the-fly generation (skip only if the generator itself fails,
         e.g. an environment without reportlab)
    """
    source_dir = OUTPUT_DIR / source
    yymm = datetime.now().strftime("%y%m")
    prebuilt = source_dir / f"test_{source}_{yymm}.pdf"
    if prebuilt.exists():
        return prebuilt
    if source_dir.exists():
        pdfs = sorted(source_dir.glob(f"test_{source}_*.pdf"))
        if pdfs:
            return pdfs[-1]

    result = subprocess.run(
        [sys.executable, str(GENERATE_SCRIPT), "--source", source],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"PDF fixture generation failed for {source}.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    pdfs = sorted(source_dir.glob(f"test_{source}_*.pdf")) if source_dir.exists() else []
    if not pdfs:
        pytest.fail(
            f"PDF generation for {source} exited 0 but produced no files in "
            f"{source_dir} — path drift between the generator and this helper."
        )
    return pdfs[-1]

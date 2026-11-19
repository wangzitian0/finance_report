from __future__ import annotations

import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

from tests.e2e.conftest import is_strict_or_ci

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DIR, OUTPUT_DIR, GENERATE_SCRIPT = (
    REPO_ROOT / "tests" / "fixtures" / "pdf" / "generated",
    REPO_ROOT / "tests" / "fixtures" / "pdf" / "output",
    REPO_ROOT / "tools" / "generate_pdf_fixtures.py",
)


def committed_fixture_pdf(name: str) -> Path:
    path = GENERATED_DIR / name
    assert path.exists(), f"committed fixture missing: {path}"
    return path


def _run_generator(source: str, *extra_args: str) -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATE_SCRIPT), "--source", source, *extra_args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        msg = f"PDF fixture generation failed for {source}.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        (pytest.fail if is_strict_or_ci() else pytest.skip)(msg)


def generated_pdf_path(source: str, period_end: date | None = None) -> Path:
    source_dir = OUTPUT_DIR / source
    if period_end is not None:
        _run_generator(source, "--period-end", period_end.isoformat())
        built = source_dir / f"test_{source}_{period_end:%y%m}.pdf"
        if not built.exists():
            pytest.fail(f"PDF generation for {source} did not write {built}")
        return built
    if (prebuilt := source_dir / f"test_{source}_{datetime.now():%y%m}.pdf").exists():
        return prebuilt
    if source_dir.exists() and (
        pdfs := sorted(source_dir.glob(f"test_{source}_*.pdf"))
    ):
        return pdfs[-1]
    _run_generator(source)
    if not source_dir.exists() or not (
        pdfs := sorted(source_dir.glob(f"test_{source}_*.pdf"))
    ):
        pytest.fail(f"PDF generation for {source} produced no files in {source_dir}")
    return pdfs[-1]

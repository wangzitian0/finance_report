from __future__ import annotations

import sys
from pathlib import Path

# Make scripts/pdf_fixtures importable for all tests in this directory.
# Using module-level insertion here (rather than a fixture) because imports in
# the test modules happen at collection time before fixtures run.
_pdf_fixtures_path = str(Path(__file__).parent.parent / "pdf_fixtures")
if _pdf_fixtures_path not in sys.path:
    sys.path.insert(0, _pdf_fixtures_path)

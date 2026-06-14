"""Drift guard for the generated env reference (Infra-014 C3).

The backend block of ``.env.example`` and ``docs/ssot/env-reference.generated.md``
are generated from ``apps/backend/src/config.py`` pydantic Settings metadata by
``tools/generate_env_reference.py``. This test runs the generator in ``--check``
mode and asserts that the committed files match the generated output, so backend
env documentation can never drift from the code.
"""

import subprocess
import sys
from pathlib import Path

# tests/infra/ -> tests/ -> backend/ -> apps/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[4]
GENERATOR = REPO_ROOT / "tools" / "generate_env_reference.py"


def test_env_reference_is_up_to_date():
    """Infra-014 C3: generated env files must equal committed files."""
    assert GENERATOR.exists(), f"generator missing: {GENERATOR}"

    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        "Generated env files are out of date. "
        "Run: python tools/generate_env_reference.py\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )

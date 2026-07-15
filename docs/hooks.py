"""MkDocs hooks for build-time generated reference pages."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "apps" / "backend"


def on_config(config, **kwargs):
    """Generate code-owned reference pages before MkDocs resolves nav files."""
    try:
        subprocess.run(
            ["uv", "run", "python", "../../tools/generate_db_schema_reference.py"],
            cwd=BACKEND_ROOT,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "MkDocs DB schema reference generation requires uv on PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "Failed to generate DB schema reference for MkDocs."
        ) from exc
    return config

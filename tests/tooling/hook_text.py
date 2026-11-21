"""AC-testing.deploy-gates.46: read the command text of one cell of runtime-hooks.manifest.json."""

from __future__ import annotations

from typing import Any


def hook_steps(manifest: Any, cell: str) -> list[str]:
    """Return one command line per check that runs in `cell`."""
    return [" ".join(check.argv) for check in manifest.checks_for_cell(cell)]


def hook_text(manifest: Any, cell: str) -> str:
    return "\n".join(hook_steps(manifest, cell))

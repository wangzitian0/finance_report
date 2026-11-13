"""AC-testing.deploy-gates.46: read the command text of a hook slot of runtime-hooks.manifest.json."""

from __future__ import annotations

from typing import Any


def hook_steps(spec: Any) -> list[str]:
    """Return one command line per check of a slot, or the single `run` line."""
    return [" ".join(check.argv) for check in spec.checks] or [spec.run]


def hook_text(spec: Any) -> str:
    return "\n".join(hook_steps(spec))

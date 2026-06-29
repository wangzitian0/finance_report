"""Resilient readers for infra2 (``repo/``) deploy-backend source.

These app-side tooling tests white-box-assert security properties (env allowlist,
no raw-response logging) on the infra2 deploy primitive's source. infra2 #425
centralized those backends from ``repo/tools/deploy_primitive.py`` into
``repo/libs/deploy/`` — a relocation that hard-coded paths could not survive.
This helper resolves the primitive source from wherever it currently lives so a
pure infra2 file move never breaks the property checks again.

The brittle white-box coupling itself (asserting infra2 internals by source
string) is tracked for a proper behavioral/contract replacement — see the issue
referenced in the bump PR.
"""

from __future__ import annotations

from pathlib import Path


def deploy_primitive_source(root: Path) -> str:
    """Return the infra2 deploy-primitive backend source, resilient to relocation.

    Prefers the legacy single file when present (``repo/tools/deploy_primitive.py``);
    otherwise returns the concatenated ``repo/libs/deploy/*.py`` backend modules
    (where infra2 #425 moved the env-allowlist / compose-update logic).
    """
    legacy = root / "repo" / "tools" / "deploy_primitive.py"
    if legacy.exists():
        return legacy.read_text()
    # infra2 #425 split the single primitive into libs/deploy/. The legacy
    # deploy_primitive.py was the PROD deploy path, whose successor is promote.py
    # (env-allowlist + compose update); preview.py is the separate preview path and
    # is deliberately excluded so single-occurrence assertions stay accurate.
    promote = root / "repo" / "libs" / "deploy" / "promote.py"
    if promote.exists():
        return promote.read_text()
    raise FileNotFoundError(
        "infra2 deploy-primitive source not found at repo/tools/deploy_primitive.py "
        "or repo/libs/deploy/promote.py — the submodule may be uninitialized or relocated again."
    )

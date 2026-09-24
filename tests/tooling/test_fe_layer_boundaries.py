"""Frontend down-only layer boundary enforcement (AC-meta.fe-contract-types.6, issue #2117).

apps/frontend/frontend-patterns.md §7 defines down-only dependency flow:
  app routes
    -> feature modules (components/<feature>/*)
      -> query helpers (hooks/*)
        -> transport (lib/api)
          -> shared API types (lib/types)
      -> UI primitives (components/ui/*)
      -> money/quantity boundaries (lib/audit/*)

Rules enforced by this gate:
1. No module under `lib/` may import from `components/` or `app/`.
2. The transport boundary `lib/api.ts` must never import React or UI components.
3. No query hook under `hooks/` may import from `app/`.
"""

from __future__ import annotations

import re
from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO / "apps" / "frontend" / "src"
LIB_DIR = FRONTEND_SRC / "lib"
HOOKS_DIR = FRONTEND_SRC / "hooks"
UI_COMPONENTS_DIR = FRONTEND_SRC / "components" / "ui"
API_TRANSPORT_FILE = LIB_DIR / "api.ts"

_IMPORT_PATTERN = re.compile(
    r"""^\s*(?:import|export)\s+(?:.*?from\s+)?['"]([^'"]+)['"]""",
    re.MULTILINE,
)


def _source_files_in(directory: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in ("*.ts", "*.tsx"):
        for path in directory.rglob(pattern):
            if "node_modules" in path.parts or "__tests__" in path.parts:
                continue
            if path.name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")):
                continue
            files.append(path)
    return sorted(files)


@ac_proof(
    proof_id="test_fe_layer_boundaries_lib_never_imports_components_or_app",
    ac_ids=["AC-meta.fe-contract-types.6"],
    ci_tier="pr_ci",
)
def test_AC_fe_layer_boundaries_1_lib_never_imports_components_or_app():
    """AC-meta.fe-contract-types.6: lib/ is a foundation layer and must not import from UI components or app routes."""
    violations: list[str] = []
    for path in _source_files_in(LIB_DIR):
        content = path.read_text(encoding="utf-8")
        for imp in _IMPORT_PATTERN.findall(content):
            if (
                "@/components" in imp
                or "components/" in imp
                or "@/app" in imp
                or "app/" in imp
            ):
                violations.append(f"{path.relative_to(REPO)} illegally imports '{imp}'")

    assert not violations, (
        "Layer boundary violation: lib/ must never depend on components/ or app/:\n"
        + "\n".join(violations)
    )


@ac_proof(
    proof_id="test_fe_layer_boundaries_api_transport_never_imports_react_or_ui",
    ac_ids=["AC-meta.fe-contract-types.6"],
    ci_tier="pr_ci",
)
def test_AC_fe_layer_boundaries_2_api_transport_never_imports_react_or_ui():
    """AC-meta.fe-contract-types.6: lib/api.ts is framework-agnostic transport and must not import React or UI."""
    assert API_TRANSPORT_FILE.exists(), f"Missing {API_TRANSPORT_FILE}"
    content = API_TRANSPORT_FILE.read_text(encoding="utf-8")
    violations: list[str] = []
    for imp in _IMPORT_PATTERN.findall(content):
        if (
            imp in ("react", "react-dom")
            or imp.startswith("react/")
            or "@/components" in imp
            or "components/" in imp
        ):
            violations.append(f"lib/api.ts illegally imports '{imp}'")

    assert not violations, (
        "Transport boundary violation: lib/api.ts must not import React or UI:\n"
        + "\n".join(violations)
    )


@ac_proof(
    proof_id="test_fe_layer_boundaries_hooks_never_import_app",
    ac_ids=["AC-meta.fe-contract-types.6"],
    ci_tier="pr_ci",
)
def test_AC_fe_layer_boundaries_3_hooks_never_import_app():
    """AC-meta.fe-contract-types.6: hooks/ must not depend on specific route pages in app/."""
    violations: list[str] = []
    for path in _source_files_in(HOOKS_DIR):
        content = path.read_text(encoding="utf-8")
        for imp in _IMPORT_PATTERN.findall(content):
            if "@/app" in imp or "app/" in imp:
                violations.append(f"{path.relative_to(REPO)} illegally imports '{imp}'")

    assert not violations, (
        "Layer boundary violation: hooks/ must never depend on app/ routes:\n"
        + "\n".join(violations)
    )


@ac_proof(
    proof_id="test_fe_layer_boundaries_ui_primitives_never_import_hooks",
    ac_ids=["AC-meta.fe-contract-types.6"],
    ci_tier="pr_ci",
)
def test_AC_fe_layer_boundaries_4_ui_primitives_never_import_hooks():
    """AC-meta.fe-contract-types.6: UI primitives under components/ui/ must not depend on query hooks in @/hooks/."""
    violations: list[str] = []
    for path in _source_files_in(UI_COMPONENTS_DIR):
        content = path.read_text(encoding="utf-8")
        for imp in _IMPORT_PATTERN.findall(content):
            if imp.startswith("@/hooks") or imp.startswith("hooks/"):
                violations.append(f"{path.relative_to(REPO)} illegally imports '{imp}'")

    assert not violations, (
        "Layer boundary violation: components/ui/ must not depend on @/hooks/:\n"
        + "\n".join(violations)
    )


def test_AC_fe_layer_boundaries_counterfactual_catches_inverted_dependencies():
    """Antagonist proof: verify that hypothetical reverse imports are caught."""
    bad_lib_import = 'import { Button } from "@/components/ui";'
    bad_hook_import = 'import Page from "@/app/(main)/dashboard/page";'
    bad_api_import = 'import { useState } from "react";'
    bad_ui_hook_import = 'import { useAccounts } from "@/hooks/useAccounts";'

    # Counterfactual 1: lib importing component
    matches_lib = [
        imp
        for imp in _IMPORT_PATTERN.findall(bad_lib_import)
        if "@/components" in imp or "components/" in imp
    ]
    assert matches_lib == ["@/components/ui"]

    # Counterfactual 2: hook importing app route
    matches_hook = [
        imp
        for imp in _IMPORT_PATTERN.findall(bad_hook_import)
        if "@/app" in imp or "app/" in imp
    ]
    assert matches_hook == ["@/app/(main)/dashboard/page"]

    # Counterfactual 3: api.ts importing react
    matches_api = [
        imp
        for imp in _IMPORT_PATTERN.findall(bad_api_import)
        if imp in ("react", "react-dom")
    ]
    assert matches_api == ["react"]

    # Counterfactual 4: UI component importing @/hooks/
    matches_ui = [
        imp
        for imp in _IMPORT_PATTERN.findall(bad_ui_hook_import)
        if imp.startswith("@/hooks") or imp.startswith("hooks/")
    ]
    assert matches_ui == ["@/hooks/useAccounts"]

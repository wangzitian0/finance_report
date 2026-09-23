"""Exhaustive governance census and ratchet enforcement (#1984).

Discovers and measures the complete application delivery and governance denominator:
- Delivery surfaces: 21 flat routers and 23 flat schemas.
- Backend composition root: 9 root modules.
- DDD units: bound vs unbound building blocks across all packages.
- API operations: OpenAPI operations, consumed operations (including semantic wrappers in api.ts), and API-only operations.
- Frontend assets: production TS/TSX surfaces.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.meta.extension.check_package_contract import discover_packages
from common.meta.extension.dependency_report import classify_operation_usage

DEFAULT_BASELINE_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "governance-ratchet-baseline.json"
)


def collect_governance_census(repo_root: Path) -> dict[str, Any]:
    """Measure the exhaustive governance denominator across backend and frontend."""
    routers_dir = repo_root / "apps/backend/src/routers"
    schemas_dir = repo_root / "apps/backend/src/schemas"
    backend_src = repo_root / "apps/backend/src"
    frontend_src = repo_root / "apps/frontend/src"

    routers = (
        sorted(
            [
                p.relative_to(repo_root).as_posix()
                for p in routers_dir.glob("*.py")
                if p.name != "__init__.py"
            ]
        )
        if routers_dir.is_dir()
        else []
    )

    schemas = (
        sorted([p.relative_to(repo_root).as_posix() for p in schemas_dir.glob("*.py")])
        if schemas_dir.is_dir()
        else []
    )

    root_modules = (
        sorted(
            [
                p.relative_to(repo_root).as_posix()
                for p in backend_src.glob("*.py")
                if p.is_file()
            ]
        )
        if backend_src.is_dir()
        else []
    )

    frontend_files = (
        sorted(
            [
                p.relative_to(repo_root).as_posix()
                for p in frontend_src.rglob("*.ts*")
                if "__tests__" not in p.parts
                and not p.name.endswith((".test.ts", ".test.tsx"))
            ]
        )
        if frontend_src.is_dir()
        else []
    )

    packages = discover_packages(repo_root)
    total_units = 0
    bound_units = 0
    unbound_units = 0
    incomplete_splits = 0
    unbound_unit_records: list[dict[str, str]] = []

    for pkg in packages:
        for unit in pkg.contract.units:
            total_units += 1
            if unit.module is not None:
                bound_units += 1
                if unit.kind.value == "repository" and unit.impl is None:
                    incomplete_splits += 1
            else:
                unbound_units += 1
                unbound_unit_records.append(
                    {"package": pkg.name, "unit": unit.name, "kind": unit.kind.value}
                )

    operations_usage = classify_operation_usage(repo_root)

    return {
        "delivery_surfaces": {
            "router_count": len(routers),
            "routers": routers,
            "schema_count": len(schemas),
            "schemas": schemas,
        },
        "backend_root_modules": {
            "count": len(root_modules),
            "modules": root_modules,
        },
        "frontend_assets": {
            "production_file_count": len(frontend_files),
        },
        "ddd_units": {
            "total_count": total_units,
            "bound_count": bound_units,
            "unbound_count": unbound_units,
            "incomplete_splits": incomplete_splits,
            "unbound_units": unbound_unit_records,
        },
        "operations": operations_usage,
    }


def verify_governance_ratchet(
    repo_root: Path,
    baseline_path: Path | None = None,
) -> dict[str, Any]:
    """Check census against baseline. Returns {'status': 'passed'|'failed', 'findings': [...]}."""
    baseline_file = baseline_path or DEFAULT_BASELINE_PATH
    if not baseline_file.is_file():
        return {
            "status": "failed",
            "findings": [f"baseline file does not exist: {baseline_file}"],
            "census": {},
        }

    baseline = json.loads(baseline_file.read_text(encoding="utf-8"))
    census = collect_governance_census(repo_root)
    findings: list[str] = []

    # Non-vacuity sentinels: empty scans fail closed
    if census["delivery_surfaces"]["router_count"] < 15:
        findings.append(
            f"vacuous router census: expected >= 15, got {census['delivery_surfaces']['router_count']}"
        )
    if census["delivery_surfaces"]["schema_count"] < 15:
        findings.append(
            f"vacuous schema census: expected >= 15, got {census['delivery_surfaces']['schema_count']}"
        )
    if census["backend_root_modules"]["count"] < 5:
        findings.append(
            f"vacuous backend root module census: expected >= 5, got {census['backend_root_modules']['count']}"
        )
    if census["frontend_assets"]["production_file_count"] < 100:
        findings.append(
            f"vacuous frontend asset census: expected >= 100, got {census['frontend_assets']['production_file_count']}"
        )
    if census["operations"]["total_operations"] < 50:
        findings.append(
            f"vacuous operations census: expected >= 50, got {census['operations']['total_operations']}"
        )

    # Shrink-only ratchet enforcement
    base_routers = set(baseline.get("delivery_surfaces", {}).get("routers", []))
    current_routers = set(census["delivery_surfaces"]["routers"])
    new_routers = sorted(current_routers - base_routers)
    if new_routers:
        findings.append(
            f"governance debt grew: new unbaselined flat routers: {new_routers}"
        )

    base_schemas = set(baseline.get("delivery_surfaces", {}).get("schemas", []))
    current_schemas = set(census["delivery_surfaces"]["schemas"])
    new_schemas = sorted(current_schemas - base_schemas)
    if new_schemas:
        findings.append(f"governance debt grew: new unbaselined schemas: {new_schemas}")

    base_root_modules = set(baseline.get("backend_root_modules", {}).get("modules", []))
    current_root_modules = set(census["backend_root_modules"]["modules"])
    new_root_modules = sorted(current_root_modules - base_root_modules)
    if new_root_modules:
        findings.append(
            f"governance debt grew: new backend root modules: {new_root_modules}"
        )

    base_unbound = baseline.get("ddd_units", {}).get("unbound_count", 0)
    current_unbound = census["ddd_units"]["unbound_count"]
    if current_unbound > base_unbound:
        findings.append(
            f"governance debt grew: unbound DDD units increased from {base_unbound} to {current_unbound}"
        )

    base_splits = baseline.get("ddd_units", {}).get("incomplete_splits", 0)
    current_splits = census["ddd_units"]["incomplete_splits"]
    if current_splits > base_splits:
        findings.append(
            f"governance debt grew: incomplete repository splits increased from {base_splits} to {current_splits}"
        )

    return {
        "status": "passed" if not findings else "failed",
        "findings": findings,
        "census": census,
        "baseline": baseline,
    }


__all__ = [
    "DEFAULT_BASELINE_PATH",
    "collect_governance_census",
    "verify_governance_ratchet",
]

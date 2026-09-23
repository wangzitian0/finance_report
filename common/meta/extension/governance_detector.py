"""Live structural detector for app and frontend governance discovery (#1984)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from common.meta.extension.governance_census import verify_governance_ratchet


def _check_app_ownership(result: dict[str, Any], repo_root: Path) -> list[str]:
    findings: list[str] = []
    census = result.get("census", {})
    baseline = result.get("baseline", {})
    base_routers = set(baseline.get("delivery_surfaces", {}).get("routers", []))
    current_routers = set(census.get("delivery_surfaces", {}).get("routers", []))
    new_routers = current_routers - base_routers
    if new_routers:
        findings.append(f"unowned application flat routers: {sorted(new_routers)}")
    base_schemas = set(baseline.get("delivery_surfaces", {}).get("schemas", []))
    current_schemas = set(census.get("delivery_surfaces", {}).get("schemas", []))
    new_schemas = current_schemas - base_schemas
    if new_schemas:
        findings.append(f"unowned application schemas: {sorted(new_schemas)}")
    return findings


def _check_domain_locality(result: dict[str, Any], repo_root: Path) -> list[str]:
    findings: list[str] = []
    census = result.get("census", {})
    baseline = result.get("baseline", {})
    base_roots = set(baseline.get("backend_root_modules", {}).get("modules", []))
    current_roots = set(census.get("backend_root_modules", {}).get("modules", []))
    new_roots = current_roots - base_roots
    if new_roots:
        findings.append(f"unauthorized root composition modules: {sorted(new_roots)}")
    return findings


def _check_python_boundary_denominator(
    result: dict[str, Any], repo_root: Path
) -> list[str]:
    census = result.get("census", {})
    count = census.get("backend_root_modules", {}).get("count", 0)
    if count == 0:
        return ["backend root module denominator is zero"]
    return []


def _check_frontend_export_denominator(
    result: dict[str, Any], repo_root: Path
) -> list[str]:
    census = result.get("census", {})
    count = census.get("frontend_assets", {}).get("production_file_count", 0)
    if count < 100:
        return [f"frontend asset denominator is below threshold: {count} < 100"]
    return []


def _check_operation_consumer_truth(
    result: dict[str, Any], repo_root: Path
) -> list[str]:
    findings: list[str] = []
    census = result.get("census", {})
    operations = census.get("operations", {})
    consumed = operations.get("consumed_operations", 0)
    if consumed < 80:
        findings.append(f"expected >= 80 consumed operations, got {consumed}")
    # Verify api.ts wrapper calls are discovered
    call_sites = operations.get("total_consumer_call_sites", 0)
    if call_sites < 130:
        findings.append(
            f"expected >= 130 frontend consumer call sites, got {call_sites}"
        )
    return findings


def _check_unused_operation_honesty(
    result: dict[str, Any], repo_root: Path
) -> list[str]:
    findings: list[str] = []
    census = result.get("census", {})
    operations = census.get("operations", {})
    total = operations.get("total_operations", 0)
    consumed = operations.get("consumed_operations", 0)
    api_only = operations.get("api_only_operations", 0)
    if total != consumed + api_only:
        findings.append(
            f"operation count discrepancy: total ({total}) != consumed ({consumed}) + api_only ({api_only})"
        )
    return findings


def _check_delivery_surface_truth(result: dict[str, Any], repo_root: Path) -> list[str]:
    findings: list[str] = []
    census = result.get("census", {})
    baseline = result.get("baseline", {})
    base_router_count = baseline.get("delivery_surfaces", {}).get("router_count", 0)
    cur_router_count = census.get("delivery_surfaces", {}).get("router_count", 0)
    if cur_router_count > base_router_count:
        findings.append(
            f"flat routers exceeded baseline: {cur_router_count} > {base_router_count}"
        )
    base_schema_count = baseline.get("delivery_surfaces", {}).get("schema_count", 0)
    cur_schema_count = census.get("delivery_surfaces", {}).get("schema_count", 0)
    if cur_schema_count > base_schema_count:
        findings.append(
            f"schemas exceeded baseline: {cur_schema_count} > {base_schema_count}"
        )
    return findings


def _check_unit_accountability(result: dict[str, Any], repo_root: Path) -> list[str]:
    findings: list[str] = []
    census = result.get("census", {})
    baseline = result.get("baseline", {})
    base_unbound = baseline.get("ddd_units", {}).get("unbound_count", 0)
    cur_unbound = census.get("ddd_units", {}).get("unbound_count", 0)
    if cur_unbound > base_unbound:
        findings.append(
            f"unbound DDD units exceeded baseline: {cur_unbound} > {base_unbound}"
        )
    base_splits = baseline.get("ddd_units", {}).get("incomplete_splits", 0)
    cur_splits = census.get("ddd_units", {}).get("incomplete_splits", 0)
    if cur_splits > base_splits:
        findings.append(
            f"incomplete repository splits exceeded baseline: {cur_splits} > {base_splits}"
        )
    return findings


def _check_non_vacuity(result: dict[str, Any], repo_root: Path) -> list[str]:
    findings: list[str] = []
    census = result.get("census", {})
    if census.get("delivery_surfaces", {}).get("router_count", 0) == 0:
        findings.append("router census is vacuous (0)")
    if census.get("delivery_surfaces", {}).get("schema_count", 0) == 0:
        findings.append("schema census is vacuous (0)")
    if census.get("ddd_units", {}).get("total_count", 0) == 0:
        findings.append("unit census is vacuous (0)")
    if census.get("operations", {}).get("total_operations", 0) == 0:
        findings.append("operation census is vacuous (0)")
    return findings


def _check_governance_integration(result: dict[str, Any], repo_root: Path) -> list[str]:
    if result.get("status") != "passed":
        return [f"governance ratchet check failed: {result.get('findings')}"]
    return []


_GUARANTEE_CHECKS = [
    ("app-ownership", _check_app_ownership),
    ("domain-locality", _check_domain_locality),
    ("python-boundary-denominator", _check_python_boundary_denominator),
    ("frontend-export-denominator", _check_frontend_export_denominator),
    ("operation-consumer-truth", _check_operation_consumer_truth),
    ("unused-operation-honesty", _check_unused_operation_honesty),
    ("delivery-surface-truth", _check_delivery_surface_truth),
    ("unit-accountability", _check_unit_accountability),
    ("non-vacuity", _check_non_vacuity),
    ("governance-integration", _check_governance_integration),
]


def detect_governance(*, repo_root: Path) -> list[dict[str, object]]:
    """Scan exhaustive governance invariants and emit detector observations."""
    ratchet_result = verify_governance_ratchet(repo_root)
    observations: list[dict[str, object]] = []

    for guarantee_id, check_fn in _GUARANTEE_CHECKS:
        try:
            findings = check_fn(ratchet_result, repo_root)
        except Exception as exc:
            findings = [f"{guarantee_id}: check raised exception: {exc}"]
        observations.append(
            {
                "guarantee_id": f"meta/{guarantee_id}",
                "current": len(findings),
                "target": 0,
                "findings": findings,
            }
        )

    return observations


__all__ = ["detect_governance"]

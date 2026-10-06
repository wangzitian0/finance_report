"""Exhaustive application and frontend governance discovery tests (#1984).

Validates the full governance denominator across backend delivery surfaces, root composition
modules, DDD unit accountability, frontend production files, and OpenAPI operation consumers.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from common.meta.extension.dependency_report import (
    classify_operation_usage,
    discover_frontend_operation_consumers,
)
from common.meta.extension.governance_census import (
    DEFAULT_BASELINE_PATH,
    collect_governance_census,
    verify_governance_ratchet,
)
from common.meta.extension.governance_detector import (
    _check_app_ownership,
    _check_delivery_surface_truth,
    _check_domain_locality,
    _check_frontend_export_denominator,
    _check_governance_integration,
    _check_non_vacuity,
    _check_operation_consumer_truth,
    _check_python_boundary_denominator,
    _check_unit_accountability,
    _check_unused_operation_honesty,
    detect_governance,
)
from common.testing.ac_proof import ac_proof

REPO_ROOT = Path(__file__).resolve().parents[2]


@ac_proof(
    "governance-ratchet-app-ownership",
    ac_ids=["AC-meta.governance-ratchet.1"],
    ci_tier="pr_ci",
    scenario_id="AC-meta.governance-ratchet.1",
    oracle_kind="deterministic_contract",
)
def test_AC_meta_governance_ratchet_1_app_ownership() -> None:
    """AC-meta.governance-ratchet.1: flat routers and schemas are ratcheted and unowned additions fail closed."""
    census = collect_governance_census(REPO_ROOT)
    baseline = json.loads(DEFAULT_BASELINE_PATH.read_text(encoding="utf-8"))

    current_routers = set(census["delivery_surfaces"]["routers"])
    base_routers = set(baseline["delivery_surfaces"]["routers"])
    assert current_routers <= base_routers, (
        f"New unratcheted routers found: {current_routers - base_routers}"
    )
    assert len(current_routers) == 21

    current_schemas = set(census["delivery_surfaces"]["schemas"])
    base_schemas = set(baseline["delivery_surfaces"]["schemas"])
    assert current_schemas <= base_schemas, (
        f"New unratcheted schemas found: {current_schemas - base_schemas}"
    )
    assert len(current_schemas) == 23

    # Counterfactual: synthetic unowned flat router triggers findings
    synthetic_result = {
        "census": {
            "delivery_surfaces": {
                "routers": list(current_routers)
                + ["apps/backend/src/routers/unauthorized_router.py"],
                "schemas": list(current_schemas),
            }
        },
        "baseline": baseline,
    }
    findings = _check_app_ownership(synthetic_result, REPO_ROOT)
    assert any("unauthorized_router.py" in f for f in findings)

    # Counterfactual: synthetic unowned schema triggers findings
    synthetic_result_schema = {
        "census": {
            "delivery_surfaces": {
                "routers": list(current_routers),
                "schemas": list(current_schemas)
                + ["apps/backend/src/schemas/unauthorized_schema.py"],
            }
        },
        "baseline": baseline,
    }
    findings_schema = _check_app_ownership(synthetic_result_schema, REPO_ROOT)
    assert any("unauthorized_schema.py" in f for f in findings_schema)


@ac_proof(
    "governance-ratchet-domain-locality",
    ac_ids=["AC-meta.governance-ratchet.2"],
    ci_tier="pr_ci",
    scenario_id="AC-meta.governance-ratchet.2",
    oracle_kind="deterministic_contract",
)
def test_AC_meta_governance_ratchet_2_domain_locality() -> None:
    """AC-meta.governance-ratchet.2: root composition modules are locked and domain escapes fail closed."""
    census = collect_governance_census(REPO_ROOT)
    baseline = json.loads(DEFAULT_BASELINE_PATH.read_text(encoding="utf-8"))

    current_roots = set(census["backend_root_modules"]["modules"])
    base_roots = set(baseline["backend_root_modules"]["modules"])
    assert current_roots == base_roots
    assert len(current_roots) == 9

    # Counterfactual: adding a domain implementation to backend root fails closed
    synthetic_result = {
        "census": {
            "backend_root_modules": {
                "modules": list(current_roots)
                + ["apps/backend/src/domain_leak_service.py"]
            }
        },
        "baseline": baseline,
    }
    findings = _check_domain_locality(synthetic_result, REPO_ROOT)
    assert any("domain_leak_service.py" in f for f in findings)


@ac_proof(
    "governance-ratchet-python-boundary-denominator",
    ac_ids=["AC-meta.governance-ratchet.3"],
    ci_tier="pr_ci",
    scenario_id="AC-meta.governance-ratchet.3",
    oracle_kind="deterministic_contract",
)
def test_AC_meta_governance_ratchet_3_python_boundary_denominator() -> None:
    """AC-meta.governance-ratchet.3: public Python composition root denominator is non-zero."""
    census = collect_governance_census(REPO_ROOT)
    root_count = census["backend_root_modules"]["count"]
    assert root_count == 9

    # Clean check returns 0 findings
    result = {"census": census}
    assert _check_python_boundary_denominator(result, REPO_ROOT) == []

    # Counterfactual: zero count fails closed
    synthetic_zero = {"census": {"backend_root_modules": {"count": 0}}}
    findings = _check_python_boundary_denominator(synthetic_zero, REPO_ROOT)
    assert findings == ["backend root module denominator is zero"]


@ac_proof(
    "governance-ratchet-frontend-export-denominator",
    ac_ids=["AC-meta.governance-ratchet.4"],
    ci_tier="pr_ci",
    scenario_id="AC-meta.governance-ratchet.4",
    oracle_kind="deterministic_contract",
)
def test_AC_meta_governance_ratchet_4_frontend_export_denominator() -> None:
    """AC-meta.governance-ratchet.4: frontend production files are comprehensively discovered."""
    census = collect_governance_census(REPO_ROOT)
    fe_count = census["frontend_assets"]["production_file_count"]
    assert fe_count >= 150, f"Expected >= 150 frontend files, got {fe_count}"

    # Clean check returns 0 findings
    result = {"census": census}
    assert _check_frontend_export_denominator(result, REPO_ROOT) == []

    # Counterfactual: artificially low count fails closed
    synthetic_low = {"census": {"frontend_assets": {"production_file_count": 42}}}
    findings = _check_frontend_export_denominator(synthetic_low, REPO_ROOT)
    assert len(findings) == 1
    assert any("below threshold: 42 < 100" in f for f in findings)


@ac_proof(
    "governance-ratchet-operation-consumer-truth",
    ac_ids=["AC-meta.governance-ratchet.5"],
    ci_tier="pr_ci",
    scenario_id="AC-meta.governance-ratchet.5",
    oracle_kind="deterministic_contract",
)
def test_AC_meta_governance_ratchet_5_operation_consumer_truth() -> None:
    """AC-meta.governance-ratchet.5: api.ts wrapper calls contribute to operation consumers and are not dead code."""
    consumers = discover_frontend_operation_consumers(REPO_ROOT)
    api_ts_call_sites = [c for c in consumers if "api.ts" in c["source"]]
    assert len(api_ts_call_sites) >= 16

    # Verify the 11 known wrapper-consumed operations are recognized
    known_wrapper_ops = {
        "create_provider_llm_providers_post",
        "delete_provider_llm_providers__provider_id__delete",
        "get_correction_loop_replay_metrics_correction_loop_replay_get",
        "get_current_user_settings_users_me_settings_get",
        "get_me_auth_me_get",
        "get_scenes_llm_scenes_get",
        "list_providers_llm_providers_get",
        "patch_current_user_settings_users_me_settings_patch",
        "put_scenes_llm_scenes_put",
        "update_base_currency_app_config_base_currency_put",
        "update_workflow_event_status_endpoint_workflow_events__event_id__patch",
    }
    discovered_ops = {c["operation_id"] for c in consumers}
    for op_id in known_wrapper_ops:
        assert op_id in discovered_ops, (
            f"Wrapper operation {op_id} was not discovered as consumed"
        )

    # Counterfactual: low consumed count fails closed
    synthetic_low_ops = {
        "census": {
            "operations": {
                "consumed_operations": 50,
                "total_consumer_call_sites": 60,
            }
        }
    }
    findings = _check_operation_consumer_truth(synthetic_low_ops, REPO_ROOT)
    assert len(findings) == 2
    assert any("expected >= 80 consumed operations" in f for f in findings)
    assert any("expected >= 130 frontend consumer call sites" in f for f in findings)


@ac_proof(
    "governance-ratchet-unused-operation-honesty",
    ac_ids=["AC-meta.governance-ratchet.6"],
    ci_tier="pr_ci",
    scenario_id="AC-meta.governance-ratchet.6",
    oracle_kind="deterministic_contract",
)
def test_AC_meta_governance_ratchet_6_unused_operation_honesty() -> None:
    """AC-meta.governance-ratchet.6: operation usage partitions cleanly into consumed and intentional API-only."""
    usage = classify_operation_usage(REPO_ROOT)
    total = usage["total_operations"]
    consumed = usage["consumed_operations"]
    api_only = usage["api_only_operations"]

    assert total == consumed + api_only, (
        f"Discrepancy: {total} != {consumed} + {api_only}"
    )
    assert total == 136
    assert consumed == 97
    assert api_only == 39

    consumed_set = set(usage["consumed_operation_ids"])
    api_only_set = set(usage["api_only_operation_ids"])
    assert consumed_set.isdisjoint(api_only_set)
    assert len(consumed_set | api_only_set) == total

    # Counterfactual: discrepancy in operation counts fails closed
    synthetic_discrepancy = {
        "census": {
            "operations": {
                "total_operations": 136,
                "consumed_operations": 90,
                "api_only_operations": 37,
            }
        }
    }
    findings = _check_unused_operation_honesty(synthetic_discrepancy, REPO_ROOT)
    assert len(findings) == 1
    assert any("operation count discrepancy" in f for f in findings)


@ac_proof(
    "governance-ratchet-delivery-surface-truth",
    ac_ids=["AC-meta.governance-ratchet.7"],
    ci_tier="pr_ci",
    scenario_id="AC-meta.governance-ratchet.7",
    oracle_kind="deterministic_contract",
)
def test_AC_meta_governance_ratchet_7_delivery_surface_truth() -> None:
    """AC-meta.governance-ratchet.7: delivery surface migration debt is shrink-only."""
    census = collect_governance_census(REPO_ROOT)
    baseline = json.loads(DEFAULT_BASELINE_PATH.read_text(encoding="utf-8"))

    cur_routers = census["delivery_surfaces"]["router_count"]
    base_routers = baseline["delivery_surfaces"]["router_count"]
    assert cur_routers <= base_routers

    cur_schemas = census["delivery_surfaces"]["schema_count"]
    base_schemas = baseline["delivery_surfaces"]["schema_count"]
    assert cur_schemas <= base_schemas

    # Counterfactual: router increase fails closed
    synthetic_router_spike = {
        "census": {
            "delivery_surfaces": {
                "router_count": base_routers + 1,
                "schema_count": base_schemas,
            }
        },
        "baseline": baseline,
    }
    findings = _check_delivery_surface_truth(synthetic_router_spike, REPO_ROOT)
    assert any("flat routers exceeded baseline" in f for f in findings)

    # Counterfactual: schema increase fails closed
    synthetic_schema_spike = {
        "census": {
            "delivery_surfaces": {
                "router_count": base_routers,
                "schema_count": base_schemas + 1,
            }
        },
        "baseline": baseline,
    }
    findings_schema = _check_delivery_surface_truth(synthetic_schema_spike, REPO_ROOT)
    assert any("schemas exceeded baseline" in f for f in findings_schema)


@ac_proof(
    "governance-ratchet-unit-accountability",
    ac_ids=["AC-meta.governance-ratchet.8"],
    ci_tier="pr_ci",
    scenario_id="AC-meta.governance-ratchet.8",
    oracle_kind="deterministic_contract",
)
def test_AC_meta_governance_ratchet_8_unit_accountability() -> None:
    """AC-meta.governance-ratchet.8: unbound DDD units and incomplete splits remain shrink-only."""
    census = collect_governance_census(REPO_ROOT)
    baseline = json.loads(DEFAULT_BASELINE_PATH.read_text(encoding="utf-8"))

    cur_unbound = census["ddd_units"]["unbound_count"]
    base_unbound = baseline["ddd_units"]["unbound_count"]
    assert cur_unbound <= base_unbound

    cur_splits = census["ddd_units"]["incomplete_splits"]
    base_splits = baseline["ddd_units"]["incomplete_splits"]
    assert cur_splits <= base_splits

    # Counterfactual: unbound unit increase fails closed
    synthetic_unbound_spike = {
        "census": {
            "ddd_units": {
                "unbound_count": base_unbound + 1,
                "incomplete_splits": base_splits,
            }
        },
        "baseline": baseline,
    }
    findings = _check_unit_accountability(synthetic_unbound_spike, REPO_ROOT)
    assert any("unbound DDD units exceeded baseline" in f for f in findings)

    # Counterfactual: incomplete split increase fails closed
    synthetic_split_spike = {
        "census": {
            "ddd_units": {
                "unbound_count": base_unbound,
                "incomplete_splits": base_splits + 1,
            }
        },
        "baseline": baseline,
    }
    findings_split = _check_unit_accountability(synthetic_split_spike, REPO_ROOT)
    assert any(
        "incomplete repository splits exceeded baseline" in f for f in findings_split
    )


@ac_proof(
    "governance-ratchet-non-vacuity",
    ac_ids=["AC-meta.governance-ratchet.9"],
    ci_tier="pr_ci",
    scenario_id="AC-meta.governance-ratchet.9",
    oracle_kind="deterministic_contract",
)
def test_AC_meta_governance_ratchet_9_non_vacuity() -> None:
    """AC-meta.governance-ratchet.9: empty or vacuous discovery passes fail closed."""
    census = collect_governance_census(REPO_ROOT)
    assert census["delivery_surfaces"]["router_count"] > 0
    assert census["delivery_surfaces"]["schema_count"] > 0
    assert census["ddd_units"]["total_count"] > 0
    assert census["operations"]["total_operations"] > 0

    clean_findings = _check_non_vacuity({"census": census}, REPO_ROOT)
    assert clean_findings == []

    # Counterfactual: completely zero census fails closed
    vacuous_census = {
        "census": {
            "delivery_surfaces": {"router_count": 0, "schema_count": 0},
            "ddd_units": {"total_count": 0},
            "operations": {"total_operations": 0},
        }
    }
    findings = _check_non_vacuity(vacuous_census, REPO_ROOT)
    assert len(findings) == 4
    expected_vacuous = {
        "router census is vacuous (0)",
        "schema census is vacuous (0)",
        "unit census is vacuous (0)",
        "operation census is vacuous (0)",
    }
    assert expected_vacuous <= set(findings)


@ac_proof(
    "governance-ratchet-governance-integration",
    ac_ids=["AC-meta.governance-ratchet.10"],
    ci_tier="pr_ci",
    scenario_id="AC-meta.governance-ratchet.10",
    oracle_kind="deterministic_contract",
)
def test_AC_meta_governance_ratchet_10_governance_integration() -> None:
    """AC-meta.governance-ratchet.10: CLI and observation provider report zero findings on clean repo."""
    # 1. verify_governance_ratchet passes
    ratchet_result = verify_governance_ratchet(REPO_ROOT)
    assert ratchet_result["status"] == "passed"
    assert ratchet_result["findings"] == []

    # 2. detect_governance emits 10 zero-finding observations
    observations = detect_governance(repo_root=REPO_ROOT)
    assert len(observations) == 10
    for obs in observations:
        assert obs["current"] == 0
        assert obs["target"] == 0
        assert obs["findings"] == []

    # 3. CLI exit code 0
    cmd = [
        sys.executable,
        str(REPO_ROOT / "tools/report_package_governance.py"),
        "--check-ratchet",
    ]
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, (
        f"CLI failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    expected_headings = [
        "## Exhaustive Governance Denominators",
        "Flat Routers",
        "Sanctioned delivery debt (shrink-only ratchet)",
    ]
    assert all(h in proc.stdout for h in expected_headings)

    # Counterfactual: failing ratchet status triggers finding
    synthetic_failed = {"status": "failed", "findings": ["simulated regression"]}
    findings = _check_governance_integration(synthetic_failed, REPO_ROOT)
    assert len(findings) == 1
    assert any("governance ratchet check failed" in f for f in findings)

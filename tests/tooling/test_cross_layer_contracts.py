from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

NON_UI_ALLOWLIST: dict[str, dict[str, object]] = {
    "health_health_get": {
        "category": "non_ui_caller",
        "method_path": "GET /health",
        "reason": "Container health probe and smoke check.",
        "proof_paths": ["common/runtime/shell/smoke_test.sh"],
    },
    "livez_livez_get": {
        "category": "non_ui_caller",
        "method_path": "GET /livez",
        "reason": "SDK container liveness probe.",
        "proof_paths": ["apps/backend/Dockerfile"],
    },
    "readyz_readyz_get": {
        "category": "non_ui_caller",
        "method_path": "GET /readyz",
        "reason": "SDK dependency readiness probe.",
        "proof_paths": ["docs/reference/api.md"],
    },
    "run_stage2_checks_reconciliation_consistency_checks_runs_post": {
        "category": "non_ui_caller",
        "method_path": "POST /reconciliation/consistency-checks/runs",
        "reason": "Benchmark runner and SSOT UC-15.",
        "proof_paths": ["tests/benchmarks/run_financial_scenario_benchmark.py", "common/meta/flows/user_cases_ssot.json"],
    },
    "post_reconciliation_adjustment_reconciliation_adjustments_post": {
        "category": "non_ui_caller",
        "method_path": "POST /reconciliation/adjustments",
        "reason": "Benchmark and E2E UC-30.",
        "proof_paths": ["tests/benchmarks/run_financial_scenario_benchmark.py", "common/meta/flows/user_cases_ssot.json"],
    },
    "list_matches_reconciliation_matches_get": {
        "category": "non_ui_caller",
        "method_path": "GET /reconciliation/matches",
        "reason": "Scenario benchmark runner.",
        "proof_paths": ["tests/benchmarks/run_financial_scenario_benchmark.py"],
    },
    "get_journal_entry_journal_entries__entry_id__get": {
        "category": "non_ui_caller",
        "method_path": "GET /journal-entries/{entry_id}",
        "reason": "Scenario benchmark runner.",
        "proof_paths": ["tests/benchmarks/run_financial_scenario_benchmark.py"],
    },
    "balance_sheet_diagnostics_reports_balance_sheet_diagnostics_get": {
        "category": "non_ui_caller",
        "method_path": "GET /reports/balance-sheet/diagnostics",
        "reason": "Benchmark and SSOT UC-40.",
        "proof_paths": ["tests/benchmarks/run_financial_scenario_benchmark.py", "common/meta/flows/user_cases_ssot.json"],
    },
    "sync_fx_endpoint_pricing_fx_syncs_post": {
        "category": "manual_replay",
        "method_path": "POST /pricing/fx/syncs",
        "reason": "Manual replay for scheduled FX sync.",
        "proof_paths": ["common/pricing/readme.md"],
    },
    "sync_stocks_endpoint_pricing_stocks_syncs_post": {
        "category": "manual_replay",
        "method_path": "POST /pricing/stocks/syncs",
        "reason": "Manual replay for scheduled stock sync.",
        "proof_paths": ["common/pricing/readme.md"],
    },
    "list_valuation_components_pricing_valuation_components_get": {
        "category": "kept_deferred",
        "method_path": "GET /pricing/valuation-components",
        "reason": "Called by benchmark case_5 and golden E2E.",
        "proof_paths": [
            "tests/benchmarks/cases/case_5.py",
            "tests/e2e/test_four_asset_net_worth_golden_path.py",
            "apps/backend/tests/assets/test_manual_valuation_snapshots.py",
        ],
    },
    "market_data_status_endpoint_pricing_market_data_status_get": {
        "category": "kept_deferred",
        "method_path": "GET /pricing/market-data/status",
        "reason": "Pricing README and staging_core_e2e.",
        "proof_paths": ["common/pricing/readme.md", "tests/e2e/test_market_data_price_paths.py"],
    },
    "create_holding_dividend_portfolio__ticker__dividends_post": {
        "category": "kept_deferred",
        "method_path": "POST /portfolio/{ticker}/dividends",
        "reason": "Deferred to #2922; called by report-package E2E.",
        "proof_paths": ["tests/e2e/test_personal_financial_report_package.py"],
    },
}


def _collect_non_test_fe_files(fe_src_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(fe_src_dir.rglob("*.ts*")):
        if not path.is_file() or path.suffix not in {".ts", ".tsx"}:
            continue
        if "__tests__" in path.parts or "node_modules" in path.parts:
            continue
        if path.name in {"api-operations.ts", "api-types.ts"}:
            continue
        files.append(path)
    return files


def _evaluate_api_surface_ratchet(
    defined_operations: set[str],
    fe_referenced_operations: set[str],
    allowlist: dict[str, dict[str, object]],
) -> dict[str, list[str]]:
    return {
        "stale_fe_references": sorted(op for op in fe_referenced_operations if op not in defined_operations),
        "unlisted_uncalled_operations": sorted(
            op for op in defined_operations if op not in fe_referenced_operations and op not in allowlist
        ),
        "stale_allowlist_entries": sorted(op for op in allowlist if op not in defined_operations),
        "fe_called_but_allowlisted": sorted(op for op in allowlist if op in fe_referenced_operations),
        "invalid_allowlist_entries": sorted(
            op
            for op, entry in allowlist.items()
            if not str(entry.get("reason", "")).strip()
            or not str(entry.get("method_path", "")).strip()
            or not entry.get("proof_paths")
        ),
    }


def test_api_surface_ratchet() -> None:
    fe_src = ROOT / "apps/frontend/src"
    ops_source = (fe_src / "lib/api-operations.ts").read_text(encoding="utf-8")
    defined = set(re.findall(r'"([a-z][a-z0-9_]*_(?:get|post|put|delete|patch))":\s*\{', ops_source))
    assert defined
    referenced: set[str] = set()
    for path in _collect_non_test_fe_files(fe_src):
        referenced.update(re.findall(r'"([a-z][a-z0-9_]*_(?:get|post|put|delete|patch))"', path.read_text(encoding="utf-8")))

    result = _evaluate_api_surface_ratchet(defined, referenced, NON_UI_ALLOWLIST)
    assert result == {
        "stale_fe_references": [],
        "unlisted_uncalled_operations": [],
        "stale_allowlist_entries": [],
        "fe_called_but_allowlisted": [],
        "invalid_allowlist_entries": [],
    }

    for op_id, entry in NON_UI_ALLOWLIST.items():
        method_path = str(entry["method_path"])
        segs = [s for s in method_path.split(" ", 1)[1].split("/") if s and not s.startswith("{")]
        tail = segs[-1] if segs else ""
        token = "/".join(segs[-2:]) if tail in {"runs", "syncs"} else tail
        assert token, f"{op_id} invalid method_path {method_path!r}"
        for rel_path in entry["proof_paths"]:  # type: ignore[attr-defined]
            target = ROOT / str(rel_path)
            assert target.exists(), f"{op_id} missing proof path {rel_path}"
            content = target.read_text(encoding="utf-8")
            assert token in content or token.replace("-", "_") in content, f"{op_id} {rel_path} missing {token}"

    rejected = _evaluate_api_surface_ratchet(defined | {"orphan_debug_probe_debug_get"}, referenced, NON_UI_ALLOWLIST)
    assert "orphan_debug_probe_debug_get" in rejected["unlisted_uncalled_operations"]
    empty_proof = _evaluate_api_surface_ratchet(
        defined | {"unproven_op_get"},
        referenced,
        {**NON_UI_ALLOWLIST, "unproven_op_get": {"category": "non_ui_caller", "method_path": "GET /x", "reason": "r", "proof_paths": []}},
    )
    assert "unproven_op_get" in empty_proof["invalid_allowlist_entries"]


def test_retired_package_routes_absent_across_frontend_docs_and_e2e() -> None:
    retired = (
        "/api/reports/package/contract",
        "/api/reports/package/readiness",
        "/api/reports/package/framework-policy",
        "/api/reports/package/annualized-income-schedule",
        "/api/reports/package/notes",
        "/api/reports/package/traceability",
    )
    assert all(
        "/api/reports/package/readiness" not in p.read_text(encoding="utf-8")
        for p in (ROOT / "apps/frontend/src").rglob("*.ts*")
    )
    for rel in (
        "common/reporting/readme.md",
        "common/reporting/framework-reporting.md",
        "common/workflow/workflow-events.md",
        "common/pricing/readme.md",
        "docs/user-guide/reports.md",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        for route in retired:
            assert route not in text, f"{rel} still references retired {route}"
    journey = (ROOT / "tests/e2e/test_personal_financial_report_package.py").read_text(encoding="utf-8")
    assert all(r.removeprefix("/api") not in journey for r in retired)


def test_cross_layer_next_config_and_ci_contracts() -> None:
    next_cfg = next(
        (p for p in (ROOT / "apps/frontend/next.config.js", ROOT / "apps/frontend/next.config.mjs") if p.exists()),
        None,
    )
    assert next_cfg is not None and any(
        tok in next_cfg.read_text(encoding="utf-8") for tok in ("rewrites", "env", "destination", "BACKEND_URL")
    )
    ci_yml = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "backend:" in ci_yml and "frontend-vitest:" in ci_yml and "ac-traceability:" not in ci_yml
    assert (ROOT / "tools/preflight.py").exists()

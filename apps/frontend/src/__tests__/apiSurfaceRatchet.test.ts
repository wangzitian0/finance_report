import { existsSync, readdirSync, readFileSync, statSync } from "fs";
import { join, resolve } from "path";
import { describe, expect, it } from "vitest";

interface AllowlistEntry {
  readonly category: "non_ui_caller" | "manual_replay" | "documented_fe_gap" | "kept_deferred";
  readonly methodPath: string;
  readonly reason: string;
  readonly proofPaths: readonly string[];
}

const RAW_ALLOWLIST: ReadonlyArray<[string, AllowlistEntry["category"], string, string, readonly string[]]> = [
  ["health_health_get", "non_ui_caller", "GET /health", "Container health probe and smoke check.", ["common/runtime/shell/smoke_test.sh"]],
  ["livez_livez_get", "non_ui_caller", "GET /livez", "SDK container liveness probe.", ["apps/backend/Dockerfile"]],
  ["readyz_readyz_get", "non_ui_caller", "GET /readyz", "SDK dependency readiness probe.", ["docs/reference/api.md"]],
  ["run_stage2_checks_reconciliation_consistency_checks_runs_post", "non_ui_caller", "POST /reconciliation/consistency-checks/runs", "Benchmark runner and SSOT UC-15.", ["tests/benchmarks/run_financial_scenario_benchmark.py", "common/meta/flows/user_cases_ssot.json"]],
  ["post_reconciliation_adjustment_reconciliation_adjustments_post", "non_ui_caller", "POST /reconciliation/adjustments", "Benchmark and E2E UC-30.", ["tests/benchmarks/run_financial_scenario_benchmark.py", "common/meta/flows/user_cases_ssot.json"]],
  ["list_matches_reconciliation_matches_get", "non_ui_caller", "GET /reconciliation/matches", "Scenario benchmark runner.", ["tests/benchmarks/run_financial_scenario_benchmark.py"]],
  ["get_journal_entry_journal_entries__entry_id__get", "non_ui_caller", "GET /journal-entries/{entry_id}", "Scenario benchmark runner.", ["tests/benchmarks/run_financial_scenario_benchmark.py"]],
  ["balance_sheet_diagnostics_reports_balance_sheet_diagnostics_get", "non_ui_caller", "GET /reports/balance-sheet/diagnostics", "Benchmark and SSOT UC-40.", ["tests/benchmarks/run_financial_scenario_benchmark.py", "common/meta/flows/user_cases_ssot.json"]],
  ["sync_fx_endpoint_pricing_fx_syncs_post", "manual_replay", "POST /pricing/fx/syncs", "Manual replay for scheduled FX sync.", ["common/pricing/readme.md"]],
  ["sync_stocks_endpoint_pricing_stocks_syncs_post", "manual_replay", "POST /pricing/stocks/syncs", "Manual replay for scheduled stock sync.", ["common/pricing/readme.md"]],
  ["list_valuation_components_pricing_valuation_components_get", "kept_deferred", "GET /pricing/valuation-components", "Called by benchmark case_5 and golden E2E.", ["tests/benchmarks/cases/case_5.py", "tests/e2e/test_four_asset_net_worth_golden_path.py", "apps/backend/tests/assets/test_manual_valuation_snapshots.py"]],
  ["market_data_status_endpoint_pricing_market_data_status_get", "kept_deferred", "GET /pricing/market-data/status", "Pricing README and staging_core_e2e.", ["common/pricing/readme.md", "tests/e2e/test_market_data_price_paths.py"]],
  ["create_holding_dividend_portfolio__ticker__dividends_post", "kept_deferred", "POST /portfolio/{ticker}/dividends", "Deferred to #2922; called by report-package E2E.", ["tests/e2e/test_personal_financial_report_package.py"]],
];

const NON_UI_ALLOWLIST: Record<string, AllowlistEntry> = Object.fromEntries(
  RAW_ALLOWLIST.map(([id, category, methodPath, reason, proofPaths]) => [id, { category, methodPath, reason, proofPaths }]),
);

function collectNonTestFeFiles(dir: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry !== "__tests__" && entry !== "node_modules") files.push(...collectNonTestFeFiles(full));
    } else if ((entry.endsWith(".ts") || entry.endsWith(".tsx")) && entry !== "api-operations.ts" && entry !== "api-types.ts") {
      files.push(full);
    }
  }
  return files;
}

function evaluateApiSurfaceRatchet(definedOperations: ReadonlySet<string>, feReferencedOperations: ReadonlySet<string>, allowlist: Readonly<Record<string, AllowlistEntry>>) {
  return {
    staleFeReferences: [...feReferencedOperations].filter((id) => !definedOperations.has(id)).sort(),
    unlistedUncalledOperations: [...definedOperations].filter((id) => !feReferencedOperations.has(id) && !(id in allowlist)).sort(),
    staleAllowlistEntries: Object.keys(allowlist).filter((id) => !definedOperations.has(id)).sort(),
    feCalledButAllowlisted: Object.keys(allowlist).filter((id) => feReferencedOperations.has(id)).sort(),
    invalidAllowlistEntries: Object.entries(allowlist)
      .filter(([, e]) => !e.reason.trim() || !e.methodPath.trim() || e.proofPaths.length === 0)
      .map(([id]) => id)
      .sort(),
  };
}

describe("API surface ratchet", () => {
  const repoRoot = resolve(__dirname, "../../../..");
  const feSrcDir = resolve(__dirname, "..");
  const opsSource = readFileSync(resolve(feSrcDir, "lib/api-operations.ts"), "utf-8");
  const definedOperations = new Set([...opsSource.matchAll(/"([a-z][a-z0-9_]*_(?:get|post|put|delete|patch))":\s*\{/g)].map((m) => m[1]));
  const feReferencedOperations = new Set(
    collectNonTestFeFiles(feSrcDir).flatMap((f) => [...readFileSync(f, "utf-8").matchAll(/"([a-z][a-z0-9_]*_(?:get|post|put|delete|patch))"/g)].map((m) => m[1])),
  );

  it("AC-meta.public-boundary.4 every operation in api-operations.ts has an FE caller or explicit allow-list reason", () => {
    expect(definedOperations.size).toBeGreaterThan(0);
    const result = evaluateApiSurfaceRatchet(definedOperations, feReferencedOperations, NON_UI_ALLOWLIST);
    expect(result.staleFeReferences).toEqual([]);
    expect(result.unlistedUncalledOperations).toEqual([]);
    expect(result.staleAllowlistEntries).toEqual([]);
    expect(result.feCalledButAllowlisted).toEqual([]);
    expect(result.invalidAllowlistEntries).toEqual([]);

    for (const [opId, entry] of Object.entries(NON_UI_ALLOWLIST)) {
      const segs = (entry.methodPath.split(" ", 2)[1] ?? "").split("/").filter((s) => s.length > 0 && !s.startsWith("{"));
      const tail = segs[segs.length - 1] ?? "";
      const token = tail === "runs" || tail === "syncs" ? segs.slice(-2).join("/") : tail;
      for (const relPath of entry.proofPaths) {
        const absPath = resolve(repoRoot, relPath);
        expect(existsSync(absPath), `${opId} missing proof path ${relPath}`).toBe(true);
        const content = readFileSync(absPath, "utf8");
        expect(content.includes(token) || content.includes(token.replaceAll("-", "_")), `${opId} ${relPath} missing ${token}`).toBe(true);
      }
    }
  });

  it("AC-meta.public-boundary.4 rejects an uncalled route added outside the allow-list", () => {
    const result = evaluateApiSurfaceRatchet(new Set([...definedOperations, "orphan_debug_probe_debug_get"]), feReferencedOperations, NON_UI_ALLOWLIST);
    expect(result.unlistedUncalledOperations).toContain("orphan_debug_probe_debug_get");
  });
});

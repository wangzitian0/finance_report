import { existsSync, readdirSync, readFileSync, statSync } from "fs";
import { join, resolve } from "path";
import { describe, expect, it } from "vitest";

interface AllowlistEntry {
  readonly category: "non_ui_caller" | "manual_replay" | "documented_fe_gap" | "kept_deferred";
  readonly methodPath: string;
  readonly reason: string;
  readonly proofPaths: readonly string[];
}

/**
 * AC-meta.public-boundary.4 (#3015, slice 6 of #3009):
 * Every OpenAPI operation in `src/lib/api-operations.ts` must either:
 *   1. Be called from non-test frontend source under `apps/frontend/src/`, OR
 *   2. Have an explicit allow-list entry here with category, reason, and existing repo proof paths.
 *
 * Adding any new backend route without a frontend caller or allow-list justification fails CI.
 */
const NON_UI_ALLOWLIST: Record<string, AllowlistEntry> = {
  // Set A (#3009): non-UI programmatic callers (infra health / benchmarks / flows SSOT)
  health_health_get: {
    category: "non_ui_caller",
    methodPath: "GET /health",
    reason: "Container health probe, staging readiness gate, and smoke check.",
    proofPaths: ["common/runtime/shell/smoke_test.sh"],
  },
  livez_livez_get: {
    category: "non_ui_caller",
    methodPath: "GET /livez",
    reason: "SDK Kubernetes/Docker container liveness probe.",
    proofPaths: ["apps/backend/Dockerfile"],
  },
  readyz_readyz_get: {
    category: "non_ui_caller",
    methodPath: "GET /readyz",
    reason: "SDK dependency readiness probe.",
    proofPaths: ["docs/reference/api.md"],
  },
  run_stage2_checks_reconciliation_consistency_checks_runs_post: {
    category: "non_ui_caller",
    methodPath: "POST /reconciliation/consistency-checks/runs",
    reason: "Financial scenario benchmark runner and SSOT UC-15 (flow 8) trigger.",
    proofPaths: [
      "tests/benchmarks/run_financial_scenario_benchmark.py",
      "common/meta/flows/user_cases_ssot.json",
    ],
  },
  post_reconciliation_adjustment_reconciliation_adjustments_post: {
    category: "non_ui_caller",
    methodPath: "POST /reconciliation/adjustments",
    reason: "Scenario benchmark and reporting E2E reconciliation adjustment UC-30 (flow 18).",
    proofPaths: [
      "tests/benchmarks/run_financial_scenario_benchmark.py",
      "common/meta/flows/user_cases_ssot.json",
    ],
  },
  list_matches_reconciliation_matches_get: {
    category: "non_ui_caller",
    methodPath: "GET /reconciliation/matches",
    reason: "Scenario benchmark runner listing accepted/pending matches.",
    proofPaths: ["tests/benchmarks/run_financial_scenario_benchmark.py"],
  },
  get_journal_entry_journal_entries__entry_id__get: {
    category: "non_ui_caller",
    methodPath: "GET /journal-entries/{entry_id}",
    reason: "Scenario benchmark runner fetching single journal entry lineage.",
    proofPaths: ["tests/benchmarks/run_financial_scenario_benchmark.py"],
  },
  balance_sheet_diagnostics_reports_balance_sheet_diagnostics_get: {
    category: "non_ui_caller",
    methodPath: "GET /reports/balance-sheet/diagnostics",
    reason: "Scenario benchmark and SSOT UC-40 (flow 24) balance-sheet diagnostics.",
    proofPaths: [
      "tests/benchmarks/run_financial_scenario_benchmark.py",
      "common/meta/flows/user_cases_ssot.json",
    ],
  },

  // Set B (#3009): manual replay endpoints for scheduled jobs ("two triggers" invariant)
  sync_fx_endpoint_pricing_fx_syncs_post: {
    category: "manual_replay",
    methodPath: "POST /pricing/fx/syncs",
    reason: "Manual replay endpoint paired with scheduled FX market-data sync.",
    proofPaths: ["common/pricing/readme.md"],
  },
  sync_stocks_endpoint_pricing_stocks_syncs_post: {
    category: "manual_replay",
    methodPath: "POST /pricing/stocks/syncs",
    reason: "Manual replay endpoint paired with scheduled stock market-data sync.",
    proofPaths: ["common/pricing/readme.md"],
  },

  // Retained in #3012 with verified active callers or explicit dependency
  list_valuation_components_pricing_valuation_components_get: {
    category: "kept_deferred",
    methodPath: "GET /pricing/valuation-components",
    reason: "Called by benchmark case_5 and golden E2E test pinned by AC8.13.42.",
    proofPaths: [
      "tests/benchmarks/cases/case_5.py",
      "tests/e2e/test_four_asset_net_worth_golden_path.py",
      "apps/backend/tests/assets/test_manual_valuation_snapshots.py",
    ],
  },
  market_data_status_endpoint_pricing_market_data_status_get: {
    category: "kept_deferred",
    methodPath: "GET /pricing/market-data/status",
    reason: "Documented in pricing README and called by staging_core_e2e market-data check.",
    proofPaths: [
      "common/pricing/readme.md",
      "tests/e2e/test_market_data_price_paths.py",
    ],
  },
  create_holding_dividend_portfolio__ticker__dividends_post: {
    category: "kept_deferred",
    methodPath: "POST /portfolio/{ticker}/dividends",
    reason: "Explicitly deferred to #2922 in #3012 and called by report-package E2E suite.",
    proofPaths: ["tests/e2e/test_personal_financial_report_package.py"],
  },
};

function parseDefinedOperationIds(operationsSource: string): Set<string> {
  const defined = new Set<string>();
  const defRe = /"([a-z][a-z0-9_]*_(?:get|post|put|delete|patch))":\s*\{/g;
  let match: RegExpExecArray | null;
  while ((match = defRe.exec(operationsSource)) !== null) {
    defined.add(match[1]);
  }
  return defined;
}

function collectNonTestFeFiles(dir: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) {
      if (entry === "__tests__" || entry === "node_modules") continue;
      files.push(...collectNonTestFeFiles(full));
    } else if (
      (entry.endsWith(".ts") || entry.endsWith(".tsx")) &&
      entry !== "api-operations.ts" &&
      entry !== "api-types.ts"
    ) {
      files.push(full);
    }
  }
  return files;
}

function parseFeReferencedOperationIds(feSrcDir: string): Set<string> {
  const referenced = new Set<string>();
  const opIdPattern = /"([a-z][a-z0-9_]*_(?:get|post|put|delete|patch))"/g;
  for (const filePath of collectNonTestFeFiles(feSrcDir)) {
    const src = readFileSync(filePath, "utf-8");
    let match: RegExpExecArray | null;
    while ((match = opIdPattern.exec(src)) !== null) {
      referenced.add(match[1]);
    }
  }
  return referenced;
}

function evaluateApiSurfaceRatchet(params: {
  definedOperations: ReadonlySet<string>;
  feReferencedOperations: ReadonlySet<string>;
  allowlist: Readonly<Record<string, AllowlistEntry>>;
}): {
  staleFeReferences: string[];
  unlistedUncalledOperations: string[];
  staleAllowlistEntries: string[];
  feCalledButAllowlisted: string[];
  invalidAllowlistEntries: string[];
} {
  const { definedOperations, feReferencedOperations, allowlist } = params;

  const staleFeReferences = [...feReferencedOperations]
    .filter((id) => !definedOperations.has(id))
    .sort();

  const unlistedUncalledOperations = [...definedOperations]
    .filter((id) => !feReferencedOperations.has(id) && !(id in allowlist))
    .sort();

  const staleAllowlistEntries = Object.keys(allowlist)
    .filter((id) => !definedOperations.has(id))
    .sort();

  const feCalledButAllowlisted = Object.keys(allowlist)
    .filter((id) => feReferencedOperations.has(id))
    .sort();

  const invalidAllowlistEntries = Object.entries(allowlist)
    .filter(([, entry]) => !entry.reason.trim() || !entry.methodPath.trim() || entry.proofPaths.length === 0)
    .map(([id]) => id)
    .sort();

  return {
    staleFeReferences,
    unlistedUncalledOperations,
    staleAllowlistEntries,
    feCalledButAllowlisted,
    invalidAllowlistEntries,
  };
}

describe("API surface ratchet", () => {
  const repoRoot = resolve(__dirname, "../../../..");
  const feSrcDir = resolve(__dirname, "..");
  const operationsSource = readFileSync(resolve(feSrcDir, "lib/api-operations.ts"), "utf-8");
  const definedOperations = parseDefinedOperationIds(operationsSource);
  const feReferencedOperations = parseFeReferencedOperationIds(feSrcDir);

  it("AC-meta.public-boundary.4 every operation in api-operations.ts has an FE caller or explicit allow-list reason", () => {
    expect(definedOperations.size).toBeGreaterThan(0);

    const result = evaluateApiSurfaceRatchet({
      definedOperations,
      feReferencedOperations,
      allowlist: NON_UI_ALLOWLIST,
    });

    expect(
      result.staleFeReferences,
      `FE references unknown operation ids: ${result.staleFeReferences.join(", ")}`,
    ).toEqual([]);
    expect(
      result.unlistedUncalledOperations,
      `New route(s) added without FE caller or NON_UI_ALLOWLIST justification: ${result.unlistedUncalledOperations.join(", ")}`,
    ).toEqual([]);
    expect(
      result.staleAllowlistEntries,
      `Allow-list contains deleted operation ids: ${result.staleAllowlistEntries.join(", ")}`,
    ).toEqual([]);
    expect(
      result.feCalledButAllowlisted,
      `Operations now called by FE must be removed from NON_UI_ALLOWLIST: ${result.feCalledButAllowlisted.join(", ")}`,
    ).toEqual([]);
    expect(
      result.invalidAllowlistEntries,
      `Allow-list entries missing reason/methodPath/proofPaths: ${result.invalidAllowlistEntries.join(", ")}`,
    ).toEqual([]);

    for (const [opId, entry] of Object.entries(NON_UI_ALLOWLIST)) {
      const pathPart = entry.methodPath.split(" ", 2)[1] ?? "";
      const segs = pathPart.split("/").filter((s) => s.length > 0 && !s.startsWith("{"));
      const tail = segs[segs.length - 1] ?? "";
      const token =
        tail === "runs" || tail === "syncs" ? segs.slice(-2).join("/") : tail;
      for (const relPath of entry.proofPaths) {
        const absPath = resolve(repoRoot, relPath);
        expect(
          existsSync(absPath),
          `Allow-list entry ${opId} references missing proof path: ${relPath}`,
        ).toBe(true);
        const content = readFileSync(absPath, "utf8");
        expect(
          content.includes(token) || content.includes(token.replaceAll("-", "_")),
          `Allow-list entry ${opId} proof path ${relPath} does not reference ${token}`,
        ).toBe(true);
      }
    }
  });

  it("AC-meta.public-boundary.4 rejects an uncalled route added outside the allow-list", () => {
    const mutatedDefined = new Set([...definedOperations, "orphan_debug_probe_debug_get"]);
    const result = evaluateApiSurfaceRatchet({
      definedOperations: mutatedDefined,
      feReferencedOperations,
      allowlist: NON_UI_ALLOWLIST,
    });

    expect(result.unlistedUncalledOperations).toContain("orphan_debug_probe_debug_get");
  });
});

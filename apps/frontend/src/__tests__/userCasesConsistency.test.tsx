import fs from "fs";
import path from "path";
import { describe, expect, it } from "vitest";

type ProofTier = "L0_GAP" | "L1_PARTIAL" | "L2_SURFACE" | "L3_BENCH" | "L3_E2E" | "L4_FULL";

interface UserCaseDefinition {
  id: string;
  legacy_flow_id: number | null;
  name: string;
  title: string;
  owning_packages: string[];
  ui_surface: string;
  component: string;
  backend_endpoint: string;
  invariant: string;
  backend_test_ref: string;
  frontend_test_ref: string;
  e2e_test_ref: string | null;
  benchmark_cases: string[];
  gap_issue: string | null;
  gap_kind?: "partial" | "gap";
}

interface SSoTRegistry {
  domains: Array<{ id: number; name: string; user_cases: UserCaseDefinition[] }>;
}

function deriveProofTier(uc: UserCaseDefinition): ProofTier {
  if (uc.gap_issue) {
    return uc.gap_kind === "gap" ? "L0_GAP" : "L1_PARTIAL";
  }
  const hasE2e = Boolean(uc.e2e_test_ref?.trim());
  const hasBench = uc.benchmark_cases.length > 0;
  if (hasE2e && hasBench) return "L4_FULL";
  if (hasE2e) return "L3_E2E";
  if (hasBench) return "L3_BENCH";
  return "L2_SURFACE";
}

function assertRealTestFile(repoRoot: string, ref: string, ucId: string): void {
  const fullPath = path.resolve(repoRoot, ref);
  expect(fs.existsSync(fullPath), `${ucId} missing ref: ${ref}`).toBe(true);
  const content = fs.readFileSync(fullPath, "utf-8");
  if (ref.endsWith(".py")) {
    expect(/^\s*(?:async\s+)?def\s+test_/m.test(content), `${ucId} has no Python test def in ${ref}`).toBe(true);
  } else {
    expect(/\b(?:it|test)\s*\(/.test(content), `${ucId} has no JS/TS test call in ${ref}`).toBe(true);
  }
}

describe("Unified 47-User-Case Frontend Consistency & SSOT Compliance Suite", () => {
  const repoRoot = path.resolve(__dirname, "../../../..");
  const registry = JSON.parse(
    fs.readFileSync(path.resolve(repoRoot, "common/meta/flows/user_cases_ssot.json"), "utf-8"),
  ) as SSoTRegistry;
  const allCases = registry.domains.flatMap((d) => d.user_cases);

  it("ensures the SSOT registry contains 8 domains, 47 user cases, and all 30 legacy flows", () => {
    expect(registry.domains).toHaveLength(8);
    expect(allCases).toHaveLength(47);
    expect(allCases.map((uc) => uc.id)).toEqual(
      Array.from({ length: 47 }, (_, i) => `UC-${String(i + 1).padStart(2, "0")}`),
    );
    const legacyIds = allCases
      .map((uc) => uc.legacy_flow_id)
      .filter((id): id is number => id !== null)
      .sort((a, b) => a - b);
    expect(legacyIds).toEqual(Array.from({ length: 30 }, (_, i) => i + 1));
  });

  it("verifies contracts, UI surfaces, derived proof tiers, and real on-disk test refs", () => {
    for (const uc of allCases) {
      expect("test_ref" in (uc as unknown as Record<string, unknown>)).toBe(false);
      expect("status" in (uc as unknown as Record<string, unknown>)).toBe(false);
      expect(uc.name.trim()).toBeTruthy();
      expect(uc.title.trim()).toBeTruthy();
      expect(uc.owning_packages.length).toBeGreaterThan(0);
      expect(uc.ui_surface.startsWith("/")).toBe(true);
      expect(uc.backend_endpoint.trim()).toBeTruthy();
      expect(uc.invariant.trim()).toBeTruthy();

      if (uc.gap_issue) {
        expect(uc.gap_issue.trim()).toBeTruthy();
        expect(["partial", "gap"]).toContain(uc.gap_kind);
      } else {
        expect(uc.gap_issue).toBeNull();
        expect(uc.gap_kind).toBeUndefined();
      }

      for (const ref of [uc.backend_test_ref, uc.frontend_test_ref, ...(uc.e2e_test_ref ? [uc.e2e_test_ref] : [])]) {
        assertRealTestFile(repoRoot, ref, uc.id);
      }
      for (const benchCase of uc.benchmark_cases) {
        const benchPath = path.resolve(repoRoot, "tests/benchmarks/cases", `case_${benchCase}.py`);
        expect(fs.existsSync(benchPath), `${uc.id} missing benchmark case: ${benchPath}`).toBe(true);
      }
    }
  });

  it("enforces aggregate proof-tier monotonicity and domain anchors", () => {
    const casesByDomain = new Map(registry.domains.map((d) => [d.id, d.user_cases]));
    const ranges: Array<[number, number, number]> = [
      [1, 1, 5],
      [2, 6, 12],
      [3, 13, 20],
      [4, 21, 25],
      [5, 26, 30],
      [6, 31, 38],
      [7, 39, 45],
      [8, 46, 47],
    ];
    for (const [domainId, start, end] of ranges) {
      expect(casesByDomain.get(domainId)?.map((u) => u.id)).toEqual(
        Array.from({ length: end - start + 1 }, (_, i) => `UC-${String(start + i).padStart(2, "0")}`),
      );
    }

    const counts: Record<ProofTier, number> = {
      L0_GAP: 0,
      L1_PARTIAL: 0,
      L2_SURFACE: 0,
      L3_BENCH: 0,
      L3_E2E: 0,
      L4_FULL: 0,
    };
    for (const uc of allCases) {
      counts[deriveProofTier(uc)] += 1;
    }
    expect(counts.L4_FULL).toBeGreaterThanOrEqual(14);
    expect(counts.L4_FULL + counts.L3_E2E).toBeGreaterThanOrEqual(21);
    expect(counts.L4_FULL + counts.L3_BENCH).toBeGreaterThanOrEqual(30);
    expect(counts.L0_GAP).toBe(0);

    const byId = (id: string) => allCases.find((u) => u.id === id);
    expect(byId("UC-14")?.component).toContain("LowConfidenceReviewModal");
    expect(byId("UC-21")?.component).toContain("UnmatchedBoard");
    expect(byId("UC-23")?.component).toContain("Stage2ReviewQueue");
    expect(byId("UC-40")?.name).toContain("Accounting Equation");
    expect(byId("UC-44")?.backend_endpoint).toBe("GET /reports/package/snapshots/{snapshot_id}/exports");
    expect(byId("UC-32")).toMatchObject({ gap_issue: "#2922", gap_kind: "partial" });
    expect(deriveProofTier(byId("UC-32")!)).toBe("L1_PARTIAL");
  });
});

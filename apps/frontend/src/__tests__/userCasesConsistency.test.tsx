import fs from "fs";
import path from "path";
import { describe, expect, it } from "vitest";

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
  status: "verified" | "partial" | "gap";
  gap_issue: string | null;
}

interface SSoTRegistry {
  domains: Array<{ id: number; name: string; user_cases: UserCaseDefinition[] }>;
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
    expect(allCases.map((uc) => uc.id)).toEqual(Array.from({ length: 47 }, (_, i) => `UC-${String(i + 1).padStart(2, "0")}`));
    const legacyIds = allCases.map((uc) => uc.legacy_flow_id).filter((id): id is number => id !== null).sort((a, b) => a - b);
    expect(legacyIds).toEqual(Array.from({ length: 30 }, (_, i) => i + 1));
  });

  it("verifies contracts, UI surfaces, honest gap tracking, and on-disk test refs", () => {
    for (const uc of allCases) {
      expect("test_ref" in (uc as unknown as Record<string, unknown>)).toBe(false);
      expect(["verified", "partial", "gap"]).toContain(uc.status);
      expect(uc.name.trim()).toBeTruthy();
      expect(uc.title.trim()).toBeTruthy();
      expect(uc.owning_packages.length).toBeGreaterThan(0);
      expect(uc.ui_surface.startsWith("/")).toBe(true);
      expect(uc.backend_endpoint.trim()).toBeTruthy();
      expect(uc.invariant.trim()).toBeTruthy();
      expect(uc.status === "verified" ? uc.gap_issue === null : Boolean(uc.gap_issue?.trim())).toBe(true);
      for (const ref of [uc.backend_test_ref, uc.frontend_test_ref, ...(uc.e2e_test_ref ? [uc.e2e_test_ref] : [])]) {
        expect(fs.existsSync(path.resolve(repoRoot, ref)), `${uc.id} missing ref: ${ref}`).toBe(true);
      }
    }
  });

  it("covers exact per-domain user-case counts and key anchors across all 8 domains", () => {
    const casesByDomain = new Map(registry.domains.map((d) => [d.id, d.user_cases]));
    const ranges: Array<[number, number, number]> = [[1, 1, 5], [2, 6, 12], [3, 13, 20], [4, 21, 25], [5, 26, 30], [6, 31, 38], [7, 39, 45], [8, 46, 47]];
    for (const [domainId, start, end] of ranges) {
      expect(casesByDomain.get(domainId)?.map((u) => u.id)).toEqual(
        Array.from({ length: end - start + 1 }, (_, i) => `UC-${String(start + i).padStart(2, "0")}`),
      );
    }
    const byId = (id: string) => allCases.find((u) => u.id === id);
    expect(byId("UC-14")?.component).toContain("LowConfidenceReviewModal");
    expect(byId("UC-21")?.component).toContain("UnmatchedBoard");
    expect(byId("UC-23")?.component).toContain("Stage2ReviewQueue");
    expect(byId("UC-40")?.name).toContain("Accounting Equation");
    expect(byId("UC-44")?.backend_endpoint).toBe("GET /reports/package/snapshots/{snapshot_id}/exports");
    expect(byId("UC-32")).toMatchObject({ status: "partial", gap_issue: "#2922" });
  });
});

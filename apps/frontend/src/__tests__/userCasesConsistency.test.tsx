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
  benchmark_cases: string[];
  status: "verified" | "partial" | "gap";
  gap_issue: string | null;
  domain_id?: number;
  domain_name?: string;
}

interface DomainDefinition {
  id: number;
  name: string;
  user_cases: UserCaseDefinition[];
}

interface SSoTRegistry {
  version: string;
  description: string;
  domains: DomainDefinition[];
}

function loadRegistry(): SSoTRegistry {
  const ssotPath = path.resolve(
    __dirname,
    "../../../../common/meta/flows/user_cases_ssot.json",
  );
  if (!fs.existsSync(ssotPath)) {
    throw new Error(`SSOT registry file not found at ${ssotPath}`);
  }
  return JSON.parse(fs.readFileSync(ssotPath, "utf-8")) as SSoTRegistry;
}

function getAllUserCases(registry: SSoTRegistry): UserCaseDefinition[] {
  const list: UserCaseDefinition[] = [];
  for (const domain of registry.domains) {
    for (const uc of domain.user_cases) {
      list.push({ ...uc, domain_id: domain.id, domain_name: domain.name });
    }
  }
  return list;
}

describe("Unified 47-User-Case Frontend Consistency & SSOT Compliance Suite", () => {
  const registry = loadRegistry();
  const allCases = getAllUserCases(registry);
  const repoRoot = path.resolve(__dirname, "../../../..");

  it("ensures the SSOT registry contains 8 domains, 47 user cases, and all 30 legacy flows", () => {
    expect(registry.domains.length).toBe(8);
    expect(allCases.length).toBe(47);
    const ids = allCases.map((uc) => uc.id);
    const expectedIds = Array.from(
      { length: 47 },
      (_, i) => `UC-${String(i + 1).padStart(2, "0")}`,
    );
    expect(ids).toEqual(expectedIds);

    const legacyIds = allCases
      .map((uc) => uc.legacy_flow_id)
      .filter((id): id is number => id !== null)
      .sort((a, b) => a - b);
    expect(legacyIds).toEqual(Array.from({ length: 30 }, (_, i) => i + 1));
  });

  it("verifies every user case has non-empty contracts, valid UI surfaces, and honest gap tracking", () => {
    for (const uc of allCases) {
      expect("test_ref" in (uc as unknown as Record<string, unknown>)).toBe(false);
      expect(["verified", "partial", "gap"]).toContain(uc.status);
      expect(uc.name.trim()).toBeTruthy();
      expect(uc.title.trim()).toBeTruthy();
      expect(uc.owning_packages.length).toBeGreaterThan(0);
      expect(uc.ui_surface.startsWith("/")).toBe(true);
      expect(uc.backend_endpoint.trim()).toBeTruthy();
      expect(uc.invariant.trim()).toBeTruthy();
      expect(uc.backend_test_ref.trim()).toBeTruthy();
      expect(uc.frontend_test_ref.trim()).toBeTruthy();
      if (uc.status === "verified") {
        expect(uc.gap_issue).toBeNull();
      } else {
        expect(uc.gap_issue?.trim()).toBeTruthy();
      }
    }
  });

  it("verifies that each referenced backend, frontend, and e2e test file exists on disk", () => {
    for (const uc of allCases) {
      const fullBackendPath = path.resolve(repoRoot, uc.backend_test_ref);
      expect(
        fs.existsSync(fullBackendPath),
        `${uc.id} backend_test_ref missing: ${uc.backend_test_ref}`,
      ).toBe(true);
      const fullFrontendPath = path.resolve(repoRoot, uc.frontend_test_ref);
      expect(
        fs.existsSync(fullFrontendPath),
        `${uc.id} frontend_test_ref missing: ${uc.frontend_test_ref}`,
      ).toBe(true);
      if (uc.e2e_test_ref) {
        const fullE2ePath = path.resolve(repoRoot, uc.e2e_test_ref);
        expect(
          fs.existsSync(fullE2ePath),
          `${uc.id} e2e_test_ref missing: ${uc.e2e_test_ref}`,
        ).toBe(true);
      }
    }
  });

  describe("Domain-specific user-case invariant validation", () => {
    const casesByDomain = new Map(
      registry.domains.map((d) => [d.id, d.user_cases]),
    );

    it("covers exact per-domain user-case counts and key anchors across all 8 domains", () => {
      expect(casesByDomain.get(1)?.map((u) => u.id)).toEqual([
        "UC-01", "UC-02", "UC-03", "UC-04", "UC-05",
      ]);
      expect(casesByDomain.get(2)?.map((u) => u.id)).toEqual([
        "UC-06", "UC-07", "UC-08", "UC-09", "UC-10", "UC-11", "UC-12",
      ]);
      expect(casesByDomain.get(3)?.map((u) => u.id)).toEqual([
        "UC-13", "UC-14", "UC-15", "UC-16", "UC-17", "UC-18", "UC-19", "UC-20",
      ]);
      expect(casesByDomain.get(4)?.map((u) => u.id)).toEqual([
        "UC-21", "UC-22", "UC-23", "UC-24", "UC-25",
      ]);
      expect(casesByDomain.get(5)?.map((u) => u.id)).toEqual([
        "UC-26", "UC-27", "UC-28", "UC-29", "UC-30",
      ]);
      expect(casesByDomain.get(6)?.map((u) => u.id)).toEqual([
        "UC-31", "UC-32", "UC-33", "UC-34", "UC-35", "UC-36", "UC-37", "UC-38",
      ]);
      expect(casesByDomain.get(7)?.map((u) => u.id)).toEqual([
        "UC-39", "UC-40", "UC-41", "UC-42", "UC-43", "UC-44", "UC-45",
      ]);
      expect(casesByDomain.get(8)?.map((u) => u.id)).toEqual([
        "UC-46", "UC-47",
      ]);

      expect(allCases.find((u) => u.id === "UC-14")?.component).toContain(
        "LowConfidenceReviewModal",
      );
      expect(allCases.find((u) => u.id === "UC-21")?.component).toContain(
        "UnmatchedBoard",
      );
      expect(allCases.find((u) => u.id === "UC-23")?.component).toContain(
        "Stage2ReviewQueue",
      );
      expect(allCases.find((u) => u.id === "UC-40")?.name).toContain(
        "Accounting Equation",
      );
      expect(allCases.find((u) => u.id === "UC-44")?.backend_endpoint).toBe(
        "GET /reports/package/snapshots/{snapshot_id}/exports",
      );
      expect(allCases.find((u) => u.id === "UC-32")?.status).toBe("partial");
      expect(allCases.find((u) => u.id === "UC-32")?.gap_issue).toBe("#2922");
    });
  });
});

import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AuditPage from "@/app/(main)/audit/page";
import { DATA_QUALITY_HEALTH_QUERY_KEY } from "@/hooks/useDataQualityHealth";
import { apiOperation } from "@/lib/api";
import { setTestUrl } from "./helpers/nextNavigation";
import * as F from "./helpers/packageTestFixtures";

vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock);
const showToastMock = vi.fn();
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast: showToastMock }) }));

const api = vi.mocked(apiOperation);
const tabs = () => within(screen.getByRole("tablist", { name: "Audit tabs" })).getAllByRole("tab");
const selTab = () => tabs().find((t) => t.getAttribute("aria-selected") === "true");

describe("Audit hub (EPIC-022 AC22.21.3)", () => {
  beforeEach(() => { api.mockReset(); F.mockAuditApi(api); setTestUrl("/audit"); });

  it("AC15.7.6 Books links and plain Needs Confirmation queue", () => F.assertAuditBooksAndQueue(api, AuditPage));
  it("AC-meta.fe-audit-queue.3 auto-selects Needs you vs Health and preserves run_id", () => F.assertAuditAutoSelect(api, AuditPage, tabs, selTab));
  it("AC-meta.fe-audit-queue.4 hides audit-ready while open items load or fail", () => F.assertAuditOpenLoading(api, AuditPage, DATA_QUALITY_HEALTH_QUERY_KEY));

  it.each([
    [{ reconciliation_stats_reconciliation_stats_get: F.auditStats(1) }, /1 transaction has no ledger match/],
    [{ get_workflow_status_endpoint_workflow_status_get: F.auditWf("blocked") }, /A blocker holds your reports/],
  ] as const)("AC-meta.fe-audit-queue.4 suppresses audit-ready grade for open items", async (ov, reason) => {
    F.mockAuditApi(api, { get_data_quality_health_reports_data_quality_get: F.AUDIT_HEALTH_A, ...ov });
    setTestUrl("/audit?tab=health"); render(<AuditPage />);
    await F.see("Open items remain"); expect(F.allTxt(reason).length).toBeGreaterThan(0); F.noTxt(/Audit[- ]Ready/i);
  });
}); // AC-ledger.fe-processing.5 AC-meta.fe-audit-queue.2

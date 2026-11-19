import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AuditPage from "@/app/(main)/audit/page";
import { ActionChecklist, InvariantChecksGrid, TemporalTimelineGrid, TrustScoreHero } from "@/components/audit/AuditPanels";
import { getGradeColor, getGradeLabel } from "@/hooks/useDataQualityHealth";
import { apiOperation } from "@/lib/api";
import type { QualityGrade } from "@/lib/types";
import * as F from "./helpers/packageTestFixtures";

vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock);
const api = vi.mocked(apiOperation);

describe("Personal Data Quality Observatory (#2294)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("renders grades, TrustScoreHero, InvariantChecksGrid, TemporalTimelineGrid, ActionChecklist", () => {
    for (const [g, l, c] of F.DQ_GRADES) { expect(getGradeLabel(g)).toBe(l); expect(getGradeColor(g)).toBe(c); }
    const h = render(<TrustScoreHero score={96} grade="A_AUDIT_READY" asOfDate="2026-10-09" currency="SGD" onRefresh={vi.fn()} />);
    expect(F.txt("Grade A · Audit-Ready")).toBeInTheDocument();
    h.rerender(<TrustScoreHero score={50} grade={"E_NOT_IN_CONTRACT" as QualityGrade} asOfDate="2026-10-09" currency="SGD" />);
    expect(F.txt("Unclassified").style.color).toBe("var(--muted)");
    render(<InvariantChecksGrid equationInvariant={F.DQ_HEALTH.equation_invariant} temporalInvariant={F.DQ_HEALTH.temporal_continuity_invariant} reconciliationInvariant={F.DQ_HEALTH.reconciliation_purity_invariant} lineageInvariant={F.DQ_HEALTH.lineage_anchors_invariant} />);
    F.has(F.DQ_INV_TEXTS);
    render(<TemporalTimelineGrid timeline={F.DQ_HEALTH.timeline} />); F.has(F.DQ_TIMELINE_TEXTS);
    const cl = render(<ActionChecklist actionItems={F.DQ_HEALTH.action_items} />);
    expect(F.txt("+10% Trust")).toBeInTheDocument();
    cl.rerender(<ActionChecklist actionItems={F.DQ_ACTION_FX} />);
    F.noTxt(/% Trust/); expect(F.lnk(/Resolve/)).toHaveAttribute("href", "/portfolio?panel=evidence");
    cl.rerender(<ActionChecklist actionItems={[]} />); expect(F.txt("All Book Checks Pass · Audit Ready")).toBeInTheDocument();
  });

  it("AuditPage observatory tabs, partial failures, and retry", () => F.runDqObsScenarios(api, AuditPage));
}); // AC-reporting.net-worth-scope.21

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import HomePage from "@/app/(main)/page";
import { apiOperation } from "@/lib/api";
import { setTestUrl } from "./helpers/nextNavigation";
import * as F from "./helpers/packageTestFixtures";

vi.mock("next/link", async () => ({ default: (await import("./helpers/packageTestFixtures")).mockLink }));
vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock);
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));

describe("HomePage", () => {
  const api = vi.mocked(apiOperation);
  beforeEach(() => { api.mockReset(); F.mockHomeApi(api); setTestUrl("/"); });

  it("AC16.12.1 AC16.12.2 loading, error fallback, and retry", () => F.assertHomeLoadingRetry(api, HomePage));
  it("AC16.12.3 AC22.1.2 AC16.12.4 AC22.4.4 AC16.12.19 cockpit metrics, zero period, lean Home", () => F.assertHomeMetricsLean(api, HomePage));
  it("AC22.16.2 AC22.5.6 AC19.4.6 AC11.8.5 audit queue, workflow/suggestions fail, scope, advisor brief", () => F.assertHomeQueueAndScope(api, HomePage));

  it.each(F.HOME_BANNER_CASES)("AC19.4.3 AC19.4.2 AC16.16.1 AC22.16.1 AC16.12.17 AC16.12.18 %s banner", async (st, act, hd, lbl, href, ord) => {
    F.mockHomeApi(api, { get_workflow_status_endpoint_workflow_status_get: F.homeWf(st, act), ...(st === "empty" ? { list_statements_statements_get: () => Promise.resolve({ items: [], total: 0 }) } : {}) });
    render(<HomePage />);
    const b = await F.fReg("Needs attention");
    expect(F.hdg(hd, undefined, b)).toBeInTheDocument();
    expect(F.lnk(lbl, b)).toHaveAttribute("href", href);
    if (ord) {
      expect(b.compareDocumentPosition(screen.getByRole("group", { name: "Report dimensions" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(screen.getByRole("group", { name: "Report dimensions" }).compareDocumentPosition(F.reg("Three-statement cockpit")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    if (st === "empty") for (const l of screen.getAllByRole("link")) expect(["/accounts", "/settings?tab=accounts"]).not.toContain(l.getAttribute("href"));
  });
}); // AC-meta.fe-app-shell.4 AC-portfolio.fe-assets2.9 AC-reporting.fe-ia-reports.1 AC-reporting.fe-ia-reports.20 AC-reporting.fe-ia-reports.21 AC-reporting.fe-ia-reports.7 AC-reporting.fe-ia-reports.9 AC-reporting.fe-remainder-reports.4 AC-reporting.fe-remainder-reports.5 AC-reporting.fe-remainder-reports.6 AC-reporting.fe-remainder-reports.9 AC-reporting.fe-report-surfaces.1 AC-reporting.fe-report-surfaces.2 AC-reporting.fe-report-surfaces.3 AC-reporting.fe-report-surfaces.4 AC-reporting.fe-report-surfaces.5 AC-reporting.fe-report-surfaces.6 AC-reporting.fe-report-surfaces.7 AC-reporting.fe-viz-reports.27 AC-reporting.net-worth-scope.5

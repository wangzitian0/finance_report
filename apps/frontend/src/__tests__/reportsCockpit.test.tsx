import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ReportsPage from "@/app/(main)/reports/page";
import { apiOperation } from "@/lib/api";
import { setTestUrl } from "./helpers/nextNavigation";
import { normalizablePackageDocument } from "./helpers/packageDocumentFixture";
import * as F from "./helpers/packageTestFixtures";

vi.mock("next/link", async () => ({ default: (await import("./helpers/packageTestFixtures")).mockLink }));
vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock);
vi.mock("@/hooks/useCurrencies", () => ({ useCurrencies: () => ({ currencies: ["SGD", "USD"], loading: false }) }));
vi.mock("@/hooks/useBaseCurrency", () => ({ useBaseCurrency: () => ({ baseCurrency: "SGD", loading: false }) }));
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const api = vi.mocked(apiOperation);

describe("Reports page (#2621 LC)", () => {
  beforeEach(() => { api.mockReset(); F.mockCockpitApi(api); setTestUrl("/reports"); });

  it("AC-reporting.fe-period-cockpit.3 AC-reporting.fe-period-cockpit.8 AC16.12.12 renders tabs, bounded series, and balance equation", () => F.assertCockpitTabsAndSeries(api, ReportsPage));
  it("AC5.37.2 AC5.37.1 handles checking, unavailable, all-clear, package-link, and all-failed states", () => F.assertCockpitEdges(api, ReportsPage));

  it("AC22.3.1 AC22.9.1 AC5.37.1 leads with readiness and statement cards without /reconciliation links", async () => {
    render(<ReportsPage />);
    const cockpit = await F.fReg("Report readiness cockpit");
    await waitFor(() => expect(cockpit).toHaveTextContent("Blocked"));
    for (const t of ["2 blockers", "2 unconfirmed items", "Pending source review"]) expect(cockpit).toHaveTextContent(t);
    expect(F.lnk("Resolve report blockers")).toHaveAttribute("href", "/journal");
    const balance = F.tid("cockpit-card-balance-sheet");
    expect(balance).toHaveTextContent("SGD 10,000");
    expect(F.tid("cockpit-card-income-statement")).toHaveTextContent("60%");
    expect(F.tid("cockpit-card-cash-flow")).toHaveTextContent("-SGD 5,000");
    expect(F.lnk("Open the balance sheet report", balance)).toHaveAttribute("href", "/reports?tab=balance-sheet");
    expect(cockpit.compareDocumentPosition(balance) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    F.noTxt("Reconciliation coverage");
    for (const link of screen.getAllByRole("link")) expect(link.getAttribute("href")).not.toMatch(/^\/reconciliation/);
  });

  it.each(F.COCKPIT_STATES)("AC5.37.1 renders %s readiness state", async (state, label, badgeClass) => {
    F.mockCockpitApi(api, () => Promise.resolve(normalizablePackageDocument({ readiness: { ...F.COCKPIT_READY, state, label } })));
    render(<ReportsPage />);
    const cockpit = await F.fReg("Report readiness cockpit");
    await waitFor(() => expect(cockpit).toHaveTextContent(`Current package state is ${label.toLowerCase()}.`));
    expect(Array.from(cockpit.querySelectorAll(".badge")).find((b) => b.textContent === label)).toHaveClass(badgeClass);
    expect(F.lnk("Open readiness path")).toHaveAttribute("href", "/journal");
  });
}); // AC-reporting.fe-ia-reports.18 AC-reporting.fe-ia-reports.2 AC-reporting.fe-ia-reports.3 AC-reporting.fe-report-surfaces.8 AC-reporting.fe-report-surfaces.9 AC-reporting.fe-viz-reports.32 AC-reporting.fe-viz-reports.33

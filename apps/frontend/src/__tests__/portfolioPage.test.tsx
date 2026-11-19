import { render, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PortfolioPage from "@/app/(main)/portfolio/page";
import * as F from "./helpers/packageTestFixtures";

const showToastMock = vi.fn();
const mockedApi = vi.hoisted(() => vi.fn());
const nav = vi.hoisted(() => ({ searchParams: new URLSearchParams(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: nav.replace, push: vi.fn() }), useSearchParams: () => nav.searchParams }));
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast: showToastMock }) }));
vi.mock("@/lib/api", async (orig) => (await import("./helpers/packageTestFixtures")).createCompatApiMock(orig, mockedApi));
vi.mock("@/components/portfolio/PortfolioSummary", () => ({
  PerformanceCard: () => <div data-testid="performance-card">PerformanceCard</div>,
  AllocationChart: ({ type, title }: { type: string; title: string }) => <div data-testid={`allocation-chart-${type}`}>{title}</div>,
}));

describe("PortfolioPage", () => {
  beforeEach(() => { mockedApi.mockReset(); showToastMock.mockReset(); nav.searchParams = new URLSearchParams(); nav.replace.mockReset(); });
  afterEach(() => vi.unstubAllGlobals());

  it("AC16.15.4 renders header, loading, error retry, and empty state", () => F.assertPortHeaderStates(mockedApi, PortfolioPage));
  it("AC16.15.5 AC17.9.3 AC17.8.4 AC17.7.5 AC5.8.1 renders table, filters, banners, and schedule", () => F.assertPortTableFilters(mockedApi, PortfolioPage));
  it("AC-portfolio.fe-panels.1 opens and closes drawers from URL params and reloads on price update", () => F.assertPortDrawersAndReload(mockedApi, nav, showToastMock, PortfolioPage));
  it("AC17.14.3 AC17.14.1 #2645 renders net-worth allocation, scope toggle, currency note, and lineage drawer", () => F.assertPortAllocationLineage(mockedApi, PortfolioPage));

  it.each(F.PORT_ALLOC_CASES)("AC17.14.3 AC11.20.3 renders allocation mode %s (%s)", async (mode, pct, expectedText, checkLink) => {
    F.mockPortfolioRouter(mockedApi, [F.PORT_H1], pct, "USD", mode);
    render(<PortfolioPage />);
    const panel = await F.fReg("Net Worth Allocation");
    expect(await within(panel).findByText(expectedText)).toBeInTheDocument();
    if (checkLink) {
      expect(within(panel).getByText("Restricted")).toBeInTheDocument();
      expect(F.lnk("401k statement", panel)).toHaveAttribute("href", "/portfolio?panel=evidence");
    }
  });
}); // AC-portfolio.fe-assets.1 AC-portfolio.fe-assets.2 AC-portfolio.fe-assets2.1 AC-portfolio.fe-assets2.16 AC-portfolio.fe-assets2.17 AC-portfolio.fe-assets2.18 AC-portfolio.fe-assets2.24 AC-portfolio.fe-net-worth-sources.1 AC-portfolio.fe-net-worth-sources.2 AC-reporting.fe-viz-reports.2

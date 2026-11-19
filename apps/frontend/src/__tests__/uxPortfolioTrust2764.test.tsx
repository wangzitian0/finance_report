import { render as R, screen as S, waitFor as W } from "@testing-library/react";
import { beforeEach, describe, expect as E, it, vi } from "vitest";
import PortfolioPage from "@/app/(main)/portfolio/page";
import { InvestmentPerformanceSchedule, formatPerformanceSourceLink } from "@/components/portfolio/InvestmentPerformanceSchedule";
import { AllocationChart, formatAllocationCategory } from "@/components/portfolio/PortfolioSummary";
import { apiOperation } from "@/lib/api";
import * as X from "./helpers/shellTestFixtures";

const nav = vi.hoisted(() => ({ searchParams: new URLSearchParams(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: nav.replace, push: vi.fn() }), useSearchParams: () => nav.searchParams }));
const showToastMock = vi.fn();
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast: showToastMock }) }));
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const api = vi.mocked(apiOperation);

describe("#2764", () => {
  beforeEach(() => { api.mockReset(); nav.searchParams = new URLSearchParams(); });
  it.each(X.PORTFOLIO_LINK_CASES)("l%#", (r, c) => E(formatPerformanceSourceLink(r)).toBe(c));

  it("schedule, donut, net-worth bars", async () => {
    const { container, unmount } = R(<InvestmentPerformanceSchedule schedule={X.makePerformanceSchedule(X.PORTFOLIO_SCHEDULE_PROPS)} />);
    X.checkPortfolioScheduleDom(container); unmount();
    E([formatAllocationCategory("Unknown", "sector"), formatAllocationCategory("", "geography")]).toEqual(["Unclassified sector", "Unclassified geography"]);
    api.mockResolvedValueOnce(X.PORTFOLIO_DONUT_MOCK);
    const v1 = R(<AllocationChart type="sector" title="Sector Allocation" />);
    await W(() => E(S.getAllByText("Unclassified sector").length).toBeGreaterThanOrEqual(1));
    E(S.queryByTestId("pie-segment-share-Technology")).toBeNull(); v1.unmount();
    X.mockApiMap(api, X.makePortfolioTrustRoutes(), []); R(<PortfolioPage />); await X.checkPortfolioTrustPanel();
  });
});

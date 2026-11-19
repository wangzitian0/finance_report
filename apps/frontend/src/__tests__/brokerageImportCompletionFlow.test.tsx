import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PortfolioPage from "@/app/(main)/portfolio/page";
import StatementDetailPage from "@/app/(main)/statements/[id]/page";
import { ToastProvider } from "@/components/ui/Toast";
import { apiOperation } from "@/lib/api";
import { BROK_STMT, fBtn, fTid, lnk, mkRouteHarness, mockBrokRouteApi, OP, see, tid, wCall, wFor } from "./helpers/statementTestFixtures";

vi.mock("@/lib/api", () => ({ apiOperation: vi.fn(), apiOperationDownload: vi.fn() }));
vi.mock("next/navigation", async () => (await import("./helpers/statementTestFixtures")).brokNavMock());
vi.mock("next/link", async () => ({ default: (await import("./helpers/statementTestFixtures")).HistoryLink }));
vi.mock("@/components/portfolio/PortfolioSummary", async () => (await import("./helpers/statementTestFixtures")).brokSummaryMock());

const RouteHarness = mkRouteHarness(PortfolioPage, StatementDetailPage);

describe("Brokerage import flow", () => {
  const api = vi.mocked(apiOperation), E = expect;
  beforeEach(() => { api.mockReset(); window.history.pushState({}, "", "/statements/s1"); mockBrokRouteApi(api, BROK_STMT); });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("AC16.15.6 AC17.8.1/2/4 imports & navigates", async () => {
    const u = userEvent.setup();
    render(<ToastProvider><RouteHarness /></ToastProvider>);
    await u.click(await fBtn(/import brokerage positions to portfolio/i));
    await wCall(api, OP.IMPORT, { body: { statement_id: "s1" } });
    E(await fTid("import-result-banner")).toHaveTextContent("Brokerage positions imported successfully");
    await u.click(lnk(/view portfolio after import/i));
    await wFor(() => E(window.location.pathname).toBe("/portfolio"));
    await see("Total Portfolio Value");
    E(tid("total-portfolio-value")).toHaveTextContent("$1,800.00");
    E(api).toHaveBeenCalledWith(OP.PORT_HOLD, E.anything());
  });
});

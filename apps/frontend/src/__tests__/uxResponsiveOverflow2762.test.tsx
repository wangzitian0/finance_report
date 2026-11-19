import { beforeEach, describe, it, vi } from "vitest";
import { HoldingsTable } from "@/components/portfolio/Holdings";
import UnmatchedBoard from "@/components/reconciliation/UnmatchedBoard";
import { BalanceSheetPanel } from "@/components/reports/StatementPanels";
import { apiOperation } from "@/lib/api";
import * as X from "./helpers/shellTestFixtures";

const nav = vi.hoisted(() => ({ searchParams: new URLSearchParams() }));
vi.mock("next/link", async () => (await import("./helpers/shellTestFixtures")).linkMock);
vi.mock("next/navigation", () => ({ useSearchParams: () => nav.searchParams }));
vi.mock("@/lib/api", () => ({ API_URL: "http://localhost:8000", apiOperation: vi.fn(), apiOperationDownload: vi.fn() }));
const api = vi.mocked(apiOperation);

describe("#2762", () => {
  beforeEach(() => { api.mockReset(); nav.searchParams = new URLSearchParams(); });
  it("overflow & nowrap", () =>
    X.runOverflowCheckAll(api, <BalanceSheetPanel filters={X.makeReportFilters({ preset: "1M", startDate: "2026-01-01", endDate: "2026-02-01" })} />, <HoldingsTable holdings={[X.OVERFLOW_HOLDING]} />, <UnmatchedBoard />));
});

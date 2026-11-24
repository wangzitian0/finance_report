import { beforeEach, describe, it, vi } from "vitest";
import { OpeningBalanceWarningBanner, ReportDimensionBar } from "@/components/reports/ReportShell";
import { readReportFilters, useReportFilters } from "@/hooks/useReportFilters";
import { apiOperation } from "@/lib/api";
import { setTestUrl, testUrl } from "./helpers/nextNavigation";
import * as X from "./helpers/shellTestFixtures";

vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock);
vi.mock("next/link", async () => (await import("./helpers/shellTestFixtures")).linkMock);
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const api = vi.mocked(apiOperation);
const Host = () => <ReportDimensionBar filters={useReportFilters()} />;

describe("#2763", () => {
  beforeEach(() => { api.mockReset(); window.localStorage.clear(); });
  it("coverage, warnings", async () => {
    await X.runCoverage2763Full(api, readReportFilters, <Host />, setTestUrl, testUrl);
    await X.runWarnings2763(<OpeningBalanceWarningBanner warnings={X.OB_WARNINGS_2763} />);
  });
});

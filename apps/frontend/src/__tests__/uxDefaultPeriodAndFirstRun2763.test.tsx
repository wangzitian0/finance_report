import { beforeEach, describe, it, vi } from "vitest";
import { FIRST_RUN_DISMISSED_KEY, FirstRunModal } from "@/components/llm/FirstRunModal";
import { OpeningBalanceWarningBanner, ReportDimensionBar } from "@/components/reports/ReportShell";
import { readReportFilters, useReportFilters } from "@/hooks/useReportFilters";
import { useLlmConfigStatus } from "@/hooks/useLlmConfigStatus";
import { apiOperation } from "@/lib/api";
import { setTestUrl, testUrl } from "./helpers/nextNavigation";
import * as X from "./helpers/shellTestFixtures";

vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock);
vi.mock("next/link", async () => (await import("./helpers/shellTestFixtures")).linkMock);
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
vi.mock("@/hooks/useLlmConfigStatus", () => ({ useLlmConfigStatus: vi.fn() }));
const api = vi.mocked(apiOperation), llm = vi.mocked(useLlmConfigStatus);
const Host = () => <ReportDimensionBar filters={useReportFilters()} />;

describe("#2763", () => {
  beforeEach(() => { api.mockReset(); llm.mockReset(); window.localStorage.clear(); });
  it("coverage, warnings, FirstRunModal", async () => {
    await X.runCoverage2763Full(api, readReportFilters, <Host />, setTestUrl, testUrl);
    llm.mockReturnValue({ configured: false, loading: false, refresh: vi.fn() });
    await X.runFirstRunAndWarnings2763(<OpeningBalanceWarningBanner warnings={X.OB_WARNINGS_2763} />, <FirstRunModal />, FIRST_RUN_DISMISSED_KEY);
  });
});

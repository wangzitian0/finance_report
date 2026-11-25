import { afterEach, beforeEach, describe, it, vi } from "vitest";
import ReportsPage from "@/app/(main)/reports/page";
import { PackageSectionCards } from "@/components/reports/package/shared";
import { personalReportPackageQuery } from "@/hooks/usePersonalReportPackage";
import { readReportFilters } from "@/hooks/useReportFilters";
import { ANALYTICS_EVENTS, track } from "@/lib/analytics";
import { setTestUrl } from "./helpers/nextNavigation";
import * as F from "./helpers/packageTestFixtures";

vi.mock(
  "next/navigation",
  async () => (await import("./helpers/nextNavigation")).nextNavigationMock,
);
vi.mock("@/hooks/useCurrencies", () => ({
  useCurrencies: () => ({ currencies: ["SGD", "USD"], loading: false }),
}));
vi.mock("@/hooks/useBaseCurrency", () => ({
  useBaseCurrency: () => ({ baseCurrency: "SGD", loading: false }),
}));
const mockedDl = vi.hoisted(() => vi.fn());
const mockedApi = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (orig) =>
  (await import("./helpers/packageTestFixtures")).createCompatApiMock(
    orig,
    mockedApi,
    mockedDl,
  ),
);
vi.mock("@/lib/analytics", async (orig) => ({
  ...(await orig<typeof import("@/lib/analytics")>()),
  track: vi.fn(),
}));

describe("PersonalReportPackagePage", () => {
  beforeEach(() => setTestUrl("/reports?tab=package"));
  afterEach(() => {
    mockedDl.mockReset();
    mockedApi.mockReset();
    vi.mocked(track).mockReset();
  });

  it("AC-reporting.package-document.12 period URL, start refresh, and snapshot reopen", () =>
    F.assertPkgPeriodAndReopen(mockedApi, readReportFilters, ReportsPage));
  it("AC8.13.92 AC20.6.1 AC22.8.3 loading, unmount, errors, abort, skeleton, print", () =>
    F.assertPkgLoadUnmountAbortPrint(mockedApi, ReportsPage));
  it("AC20.6.1 AC20.7.1 AC22.8.1 AC22.8.2 AC22.13.3 #2645 framework gate, TOC, leap year, scope", () =>
    F.assertPkgGateTocLeapScope(mockedApi, ReportsPage));
  it("AC5.17.2 AC5.19.4 AC22.18.3 snapshots, exports, analytics, errors, timestamps", () =>
    F.assertPkgSnapshotsExports(
      mockedApi,
      mockedDl,
      track,
      ANALYTICS_EVENTS.REPORT_GENERATED,
      ReportsPage,
    ));
  it("AC20.6.1 HK-like package and stale aborted US-like guard", () =>
    F.assertPkgHkAbortGuard(mockedApi, ReportsPage));
  it("AC19.5.4 AC19.5.5 AC19.9.2 AC22.19.1 AC22.19.2 AC22.19.3 AC5.9.4 AC5.11.2 AC5.12.3 AC5.13.3 #2727 sections, basis, disclosures", () =>
    F.assertPkgSectionsAndAudit(mockedApi, ReportsPage));
  it("AC-reporting.package-document.3 AC-reporting.fe-fetch-budget.7 lazy line-details, manifest paging, empty/errors", () =>
    F.assertPkgLazyDetailsManifest(mockedApi, ReportsPage));
  it("AC18.9.4 AC18.9.5 AC18.9.6 AC18.9.3 Evidence Lineage dialog, missing anchor, error, source mapping", () =>
    F.assertPkgLineageAndMapping(mockedApi, ReportsPage));
  it("AC-reporting.fe-fetch-budget.9 policy decisions lazy load, paging, errors, empty, no-anchor, snapshot", () =>
    F.assertPkgPolicyPaging(mockedApi, ReportsPage));
  it("AC-reporting.fe-fetch-budget.5 shared preview cache, stale period hold, framework switch, snapshot invalidation", () =>
    F.assertPkgSharedCacheAndHold(
      mockedApi,
      personalReportPackageQuery,
      readReportFilters,
      ReportsPage,
    ));
});

describe("PackageSectionCards", () => {
  it("#2645 discloses opening coverage, revoked evidence, excluded holdings, and missing scope", () =>
    F.assertPkgSectionCardsScope(PackageSectionCards as never));
}); // AC-portfolio.fe-assets2.10 AC-portfolio.fe-assets2.7 AC-portfolio.fe-assets2.8 AC-reporting.fe-ia-reports.14 AC-reporting.fe-ia-reports.15 AC-reporting.fe-ia-reports.16 AC-reporting.fe-ia-reports.23 AC-reporting.fe-ia-reports.24 AC-reporting.fe-ia-reports.25 AC-reporting.fe-remainder-reports.1 AC-reporting.fe-remainder-reports.11 AC-reporting.fe-remainder-reports.12 AC-reporting.fe-remainder-reports.14 AC-reporting.fe-remainder-reports.2 AC-reporting.fe-remainder-reports.3 AC-reporting.fe-viz-reports.1 AC-reporting.fe-viz-reports.10 AC-reporting.fe-viz-reports.11 AC-reporting.fe-viz-reports.12 AC-reporting.fe-viz-reports.3 AC-reporting.fe-viz-reports.4 AC-reporting.fe-viz-reports.5 AC-reporting.fe-viz-reports.6 AC-reporting.fe-viz-reports.7 AC-reporting.net-worth-scope.15 AC-reporting.net-worth-scope.17 AC-reporting.net-worth-scope.23 AC-reporting.report-integrity.3

import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FIRST_RUN_DISMISSED_KEY, FirstRunModal } from "@/components/llm/FirstRunModal";
import { OpeningBalanceWarningBanner, ReportDimensionBar } from "@/components/reports/ReportShell";
import { readReportFilters, useReportFilters } from "@/hooks/useReportFilters";
import { useLlmConfigStatus } from "@/hooks/useLlmConfigStatus";
import { apiOperation } from "@/lib/api-client";

import { setTestUrl, testUrl } from "./helpers/nextNavigation";

vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock);
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));
vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
}));
vi.mock("@/hooks/useLlmConfigStatus", () => ({
  useLlmConfigStatus: vi.fn(),
}));

const mockedApiOperation = vi.mocked(apiOperation);
const mockedLlmStatus = vi.mocked(useLlmConfigStatus);
const refresh = vi.fn();

function DimensionBarHost() {
  const filters = useReportFilters();
  return <ReportDimensionBar filters={filters} />;
}

describe("Issue #2763: report coverage notes, opening balance warnings, and FirstRunModal persistence", () => {
  beforeEach(() => {
    mockedApiOperation.mockReset();
    mockedLlmStatus.mockReset();
    refresh.mockReset();
    window.localStorage.clear();
  });

  // AC-reporting.fe-period-cockpit.7 / AC-reporting.2726.2
  it("AC-reporting.fe-period-cockpit.7 keeps coverageLimitingAccounts and report-coverage-note visible for All and after jumping to latestStatementEnd", async () => {
    const today = new Date(2026, 9, 27);
    const coverage = {
      start: "2025-03-01",
      limitingAccounts: ["DBS Multi-Currency USD", "Wise EUR Vault"],
      latestStatementEnd: "2025-03-31",
    };

    const allFilters = readReportFilters(new URLSearchParams("period=All"), today, coverage);
    expect(allFilters.opensAtCoverageStart).toBe(true);
    expect(allFilters.coverageLimitingAccounts).toEqual(["DBS Multi-Currency USD", "Wise EUR Vault"]);

    const jumpedFilters = readReportFilters(new URLSearchParams("end=2025-03-31"), today, coverage);
    expect(jumpedFilters.opensAtCoverageStart).toBe(true);
    expect(jumpedFilters.startDate).toBe("2025-03-01");
    expect(jumpedFilters.endDate).toBe("2025-03-31");
    expect(jumpedFilters.coverageLimitingAccounts).toEqual(["DBS Multi-Currency USD", "Wise EUR Vault"]);

    mockedApiOperation.mockImplementation(((operationId: string, request?: { query?: { as_of_date?: string } }) => {
      if (operationId === "report_coverage_reports_coverage_get") {
        return Promise.resolve({
          as_of_date: request?.query?.as_of_date,
          coverage_start: "2025-03-01",
          limiting_accounts: ["DBS Multi-Currency USD", "Wise EUR Vault"],
          latest_statement_end: "2025-03-31",
        });
      }
      if (operationId === "get_available_currencies_reports_currencies_get") return Promise.resolve(["SGD"]);
      if (operationId === "get_base_currency_app_config_base_currency_get") return Promise.resolve({ base_currency: "SGD" });
      return Promise.reject(new Error(`unexpected ${operationId}`));
    }) as never);

    setTestUrl("/reports");
    render(<DimensionBarHost />);

    const banner = await screen.findByTestId("report-latest-statement-banner");
    expect(banner).toHaveAttribute("role", "status");
    expect(banner).toHaveTextContent("Latest statement ends Mar 31, 2025, before this period.");

    fireEvent.click(screen.getByRole("button", { name: "Jump to Mar 31, 2025" }));
    expect(testUrl()).toBe("/reports?end=2025-03-31");

    const note = await screen.findByTestId("report-coverage-note");
    expect(note).toHaveTextContent(
      "Starts Mar 1, 2025: DBS Multi-Currency USD and Wise EUR Vault have no opening balance before this date.",
    );
  });

  // AC-reporting.fe-report-surfaces.1
  it("AC-reporting.fe-report-surfaces.1 renders all distinct account messages in OpeningBalanceWarningBanner when multiple warnings exist", () => {
    render(
      <OpeningBalanceWarningBanner
        warnings={[
          {
            type: "missing_opening_balance",
            account_name: "DBS Multi-Currency USD",
            message: "No opening balance recorded before 2025-03-01.",
          },
          {
            type: "missing_opening_balance",
            account_name: "Wise EUR Vault",
            earliest_activity_date: "2025-03-10",
          },
        ]}
      />,
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("DBS Multi-Currency USD: No opening balance recorded before 2025-03-01.");
    expect(alert).toHaveTextContent("Wise EUR Vault has no opening balance before 2025-03-10.");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  // AC-meta.fe-app-shell.1
  it("AC-meta.fe-app-shell.1 persists FirstRunModal dismissal in localStorage across remounts and tucks protocol/base URL under Advanced settings", () => {
    mockedLlmStatus.mockReturnValue({ configured: false, loading: false, refresh });

    const firstRender = render(<FirstRunModal />);
    expect(screen.getByText("Set up your AI provider")).toBeInTheDocument();

    const advanced = screen.getByTestId("provider-advanced-settings") as HTMLDetailsElement;
    expect(advanced.tagName).toBe("DETAILS");
    expect(advanced.open).toBe(false);
    expect(screen.getByText("Advanced connection settings")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Cancel/i }));
    expect(window.localStorage.getItem(FIRST_RUN_DISMISSED_KEY)).toBe("true");
    expect(screen.queryByText("Set up your AI provider")).not.toBeInTheDocument();
    firstRender.unmount();

    const secondRender = render(<FirstRunModal />);
    expect(secondRender.container).toBeEmptyDOMElement();
  });
});

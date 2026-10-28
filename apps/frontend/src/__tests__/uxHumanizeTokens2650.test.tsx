import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { AdvisorBrief } from "@/components/advisor/AdvisorBrief";
import { PackagePanel } from "@/components/reports/PackagePanel";
import { PackageCover } from "@/components/reports/package/shared";
import { AccountsPanel } from "@/components/settings/SettingsPanels";
import { apiOperation } from "@/lib/api-client";
import { formatAccountCodeBadge } from "@/lib/statusLabels";
import type { AccountListResponse, AdvisorSuggestion, PersonalReportPackageContractResponse } from "@/lib/types";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: vi.fn() }),
}));

vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
  apiOperationDownload: vi.fn(),
}));

const mockedUsePersonalReportPackage = vi.fn();
vi.mock("@/hooks/usePersonalReportPackage", () => ({
  usePersonalReportPackage: (...args: unknown[]) => mockedUsePersonalReportPackage(...args),
  generatePackageSnapshot: vi.fn(),
  invalidateReportPackageQueries: vi.fn(),
}));

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = "UxHumanizeTokensWrapper";
  return Wrapper;
}

describe("Issue #2650 — humanize internal tokens across Advisor, Package, and Settings", () => {
  // AC-advisor.fe-remainder-chat.2
  it("AC21.3.2 humanizes snake_case confidence_tier and source_refs badges in AdvisorBrief", () => {
    const suggestions: AdvisorSuggestion[] = [
      {
        basis: "Two items need review before relying on package readiness.",
        confidence_tier: "review_required",
        source_refs: ["report_readiness", "authority_coverage", "market_data", "cash_flow"],
        limitation: "Unreviewed items can shift totals.",
        next_action_href: "/review",
      },
      {
        basis: "Ledger totals are reconciled.",
        confidence_tier: "deterministic",
        source_refs: ["workflow.status", "reconciliation"],
        limitation: "Reflects posted entries only.",
        next_action_href: "/reports",
      },
    ];

    render(<AdvisorBrief suggestions={suggestions} />);

    const card0 = screen.getByTestId("advisor-brief-card-0");
    expect(within(card0).getByText("Review Required")).toBeInTheDocument();
    expect(within(card0).getByText("Report Readiness")).toBeInTheDocument();
    expect(within(card0).getByText("Authority Coverage")).toBeInTheDocument();
    expect(within(card0).getByText("Market Data")).toBeInTheDocument();
    expect(within(card0).getByText("Cash Flow")).toBeInTheDocument();

    expect(within(card0).queryByText("review_required")).toBeNull();
    expect(within(card0).queryByText("report_readiness")).toBeNull();
    expect(within(card0).queryByText("authority_coverage")).toBeNull();
    expect(within(card0).queryByText("market_data")).toBeNull();
    expect(within(card0).queryByText("cash_flow")).toBeNull();

    const card1 = screen.getByTestId("advisor-brief-card-1");
    expect(within(card1).getByText("Deterministic")).toBeInTheDocument();
    expect(within(card1).getByText("Workflow Status")).toBeInTheDocument();
    expect(within(card1).getByText("Reconciliation")).toBeInTheDocument();
  });

  // AC-reporting.fe-ia-reports.15
  it("AC22.8.2 humanizes package_id slug in PackageCover and renders PackageLoadingSkeleton on cold cache in PackagePanel", () => {
    const contract: PersonalReportPackageContractResponse = {
      package_id: "personal-financial-report-package",
      version: "1.0.0",
      period_semantics: {
        start_date: "required for period sections",
        end_date: "required for period sections",
        as_of_date: "required for point-in-time sections",
      },
      supported_frameworks: [],
      selected_framework_id: null,
      sections: [],
      export_contract: {
        formats: ["json", "csv"],
        csv_columns: ["package_id", "section_id"],
      },
    };

    render(
      <PackageCover
        contract={contract}
        reportDate="2026-05-20"
        startDate="2025-05-20"
        selectedFrameworkLabel="US-like"
      />,
    );

    const cover = screen.getByRole("region", { name: "Report package cover" });
    expect(within(cover).getByText("Personal Financial Report Package")).toBeInTheDocument();
    expect(within(cover).queryByText("personal-financial-report-package")).toBeNull();

    mockedUsePersonalReportPackage.mockReturnValue({
      contract: null,
      document: null,
      packageSnapshots: [],
      isPackageRefreshing: false,
      isPackageLoading: true,
      error: null,
    });

    const { container } = render(
      <PackagePanel
        filters={{
          tab: "package",
          preset: "1Y",
          startDate: "2025-05-20",
          endDate: "2026-05-20",
          isCurrent: false,
          currency: "SGD",
          includeRestricted: true,
          openingDate: "2025-05-19",
          isDefaultPeriod: true,
          opensAtCoverageStart: false,
          coverageLimitingAccounts: [],
          latestStatementEnd: null,
          previousEnd: "2025-05-20",
          nextEnd: null,
          dimensionQuery: "",
          ready: true,
        }}
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByRole("status", { name: "Loading report package" })).toHaveAttribute("aria-busy", "true");
    expect(container.querySelectorAll("[data-testid='skeleton-block']").length).toBeGreaterThanOrEqual(10);
  });

  it("maps internal system account codes while preserving user-defined accounting codes in AccountsPanel", async () => {
    expect(formatAccountCodeBadge("AUTO-ASSET")).toBe("Auto-created");
    expect(formatAccountCodeBadge("SYS-PROCESSING")).toBe("System clearing");
    expect(formatAccountCodeBadge("AUTO-EQUITY-OPENING")).toBe("Opening equity");
    expect(formatAccountCodeBadge("AUTO-BANK")).toBe("Auto bank");
    expect(formatAccountCodeBadge("1001")).toBe("1001");
    expect(formatAccountCodeBadge("2100")).toBe("2100");

    const mockedApi = vi.mocked(apiOperation);
    mockedApi.mockImplementation((operationId: string) => {
      if (operationId === "get_opening_balance_readiness_status_accounts_opening_balance_readiness_get") {
        return Promise.resolve({ needs_opening_balance: false });
      }
      return Promise.resolve({
        items: [
          {
            id: "acc-auto-asset",
            name: "Brokerage Custody",
            code: "AUTO-ASSET",
            type: "ASSET",
            currency: "SGD",
            is_active: true,
            balance: "1500",
            is_system: false,
            user_id: "u1",
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
          {
            id: "acc-sys-proc",
            name: "Processing",
            code: "SYS-PROCESSING",
            type: "ASSET",
            currency: "SGD",
            is_active: true,
            balance: "0",
            is_system: true,
            user_id: "u1",
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
          {
            id: "acc-user-code",
            name: "Operating Cash",
            code: "1001",
            type: "ASSET",
            currency: "SGD",
            is_active: true,
            balance: "2500",
            is_system: false,
            user_id: "u1",
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ],
        total: 3,
      } satisfies AccountListResponse);
    });

    render(<AccountsPanel />, { wrapper: createWrapper() });

    await waitFor(() => expect(screen.getByText("Brokerage Custody")).toBeInTheDocument());
    expect(screen.getByText("Auto-created")).toBeInTheDocument();
    expect(screen.getByText("System clearing")).toBeInTheDocument();
    expect(screen.getByText("1001")).toBeInTheDocument();
    expect(screen.queryByText("AUTO-ASSET")).toBeNull();
    expect(screen.queryByText("SYS-PROCESSING")).toBeNull();
  });
});

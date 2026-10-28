import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import AuditPage from "@/app/(main)/audit/page";
import ChatPage from "@/app/(main)/chat/page";
import HomePage from "@/app/(main)/page";
import PortfolioPage from "@/app/(main)/portfolio/page";
import ReportsPage from "@/app/(main)/reports/page";
import StatementReviewPage from "@/app/(main)/statements/[id]/page";
import UploadPage from "@/app/(main)/upload/page";
import { AdvisorBrief } from "@/components/advisor/AdvisorBrief";
import { PackagePanel } from "@/components/reports/CashFlowAndPackagePanels";
import { PackageCover } from "@/components/reports/package/shared";
import { AccountsPanel } from "@/components/settings/SettingsPanels";
import { humanizeWorkflowText } from "@/components/workflow/workflowFormat";
import { apiOperation } from "@/lib/api-client";
import { formatAccountCodeBadge } from "@/lib/statusLabels";
import { setTestUrl } from "./helpers/nextNavigation";
import type { AccountListResponse, AdvisorSuggestion, PersonalReportPackageContractResponse } from "@/lib/types";

vi.mock("next/navigation", async () => {
  const { nextNavigationMock } = await import("./helpers/nextNavigation");
  return {
    ...nextNavigationMock,
    useParams: () => ({ id: "stmt-1" }),
  };
});

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    scroll: _scroll,
    ...props
  }: {
    href: string;
    children: ReactNode;
    scroll?: boolean;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const mockShowToast = vi.fn();
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: mockShowToast }),
}));

vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
  apiOperationDownload: vi.fn(),
  apiOperationStream: vi.fn(),
  confirmStatementReviewEnvelope: vi.fn(),
}));

vi.mock("@/lib/aiModels", () => ({
  fetchAiModels: vi.fn().mockResolvedValue({
    default_model: "gpt-4o",
    models: [{ id: "gpt-4o", name: "GPT-4o", is_free: true }],
  }),
}));

const mockedUsePersonalReportPackage = vi.fn();
vi.mock("@/hooks/usePersonalReportPackage", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/usePersonalReportPackage")>();
  return {
    ...actual,
    usePersonalReportPackage: (...args: unknown[]) => mockedUsePersonalReportPackage(...args),
    generatePackageSnapshot: vi.fn(),
    invalidateReportPackageQueries: vi.fn(),
  };
});

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

  it("pluralizes (s) tokens in humanizeWorkflowText and AdvisorBrief without mutating backend fixtures", () => {
    expect(humanizeWorkflowText("1 statement(s) waiting for review")).toBe("1 statement waiting for review");
    expect(humanizeWorkflowText("2 statement(s) waiting for review")).toBe("2 statements waiting for review");
    expect(humanizeWorkflowText("Market data is stale for 1 observed scope(s).")).toBe(
      "Market data is stale for 1 observed scope.",
    );
    expect(humanizeWorkflowText("Workflow has 2 action-required event(s).")).toBe(
      "Workflow has 2 action-required events.",
    );
    expect(humanizeWorkflowText("Pending statement(s) need attention")).toBe("Pending statements need attention");

    render(
      <AdvisorBrief
        suggestions={[
          {
            basis: "1 statement(s) waiting for review in report_readiness.",
            confidence_tier: "review_required",
            source_refs: ["report_readiness"],
            limitation: "Market data is stale for 1 observed scope(s).",
            next_action_href: "/upload",
          },
        ]}
      />,
    );

    expect(screen.getByText("1 statement waiting for review in report readiness.")).toBeInTheDocument();
    expect(screen.getByText("Market data is stale for 1 observed scope.")).toBeInTheDocument();
  });

  it("renders the 7 everyday screens (Home, Upload, Statement, Audit, Reports, Portfolio, Chat) with 0 banned jargon matches", async () => {
    const bannedJargon =
      /\b(invariant|invariants|rollforward|source envelope|reviewed disposition|economic intent|held-out|leakage)\b|\b[a-z]+_[a-z_]+\b|\(s\)/i;

    const extractVisibleText = (container: HTMLElement): string => {
      const clone = container.cloneNode(true) as HTMLElement;
      clone.querySelectorAll("[aria-hidden='true'], .hidden").forEach((node) => node.remove());
      return clone.textContent ?? "";
    };

    const mockedApi = vi.mocked(apiOperation);
    mockedApi.mockImplementation(async (operationId: string) => {
      switch (operationId) {
        case "get_user_currency_users_me_currency_get":
          return { currency: "SGD" };
        case "get_workflow_status_endpoint_workflow_status_get":
          return {
            primary_state: "needs_action",
            next_action: {
              type: "review_required",
              count: 1,
              href: "/upload",
              label: "Review statement",
              summary: "1 statement(s) waiting for review",
            },
            report_readiness: { state: "ready", blocking_count: 0, href: "/reports" },
            event_counts: { unread: 1, action_required: 1, blocked: 0 },
          };
        case "list_workflow_events_endpoint_workflow_events_get":
          return {
            items: [
              {
                id: "evt-1",
                session_id: "sess-1",
                event_type: "statement_parsed",
                severity: "action_required",
                status: "unread",
                title: "1 statement(s) waiting for review",
                summary: "Package section invariant failed: opening_balance_missing",
                action_href: "/upload",
                occurred_at: "2026-05-20T10:00:00Z",
              },
            ],
            sessions: [],
            total: 1,
          };
        case "suggestions_chat_suggestions_get":
          return {
            suggestions: ["Summarize this month"],
            structured_suggestions: [
              {
                basis: "1 statement(s) waiting for review.",
                confidence_tier: "review_required",
                source_refs: ["report_readiness", "authority_coverage"],
                limitation: "Market data is stale for 1 observed scope(s).",
                next_action_href: "/upload",
              },
            ],
          };
        case "chat_history_chat_history_get":
          return { sessions: [] };
        case "list_statements_statements_get":
          return {
            items: [
              {
                id: "stmt-1",
                institution: "DBS",
                original_filename: "DBS_May_2026.csv",
                status: "parsed",
                currency: "SGD",
                period_start: "2026-05-01",
                period_end: "2026-05-31",
                opening_balance: "1000.00",
                closing_balance: "1200.00",
                confidence_score: 92,
                balance_validated: true,
                transactions: [],
              },
            ],
            total: 1,
          };
        case "get_statement_statements__statement_id__get":
          return {
            id: "stmt-1",
            institution: "DBS",
            original_filename: "DBS_May_2026.csv",
            status: "parsed",
            currency: "SGD",
            period_start: "2026-05-01",
            period_end: "2026-05-31",
            opening_balance: "1000.00",
            closing_balance: "1200.00",
            confidence_score: 92,
            balance_validated: true,
            transactions: [
              {
                id: "txn-1",
                txn_date: "2026-05-10",
                description: "Coffee Shop",
                amount: "12.50",
                direction: "OUT",
                currency: "SGD",
                status: "pending",
                confidence: "high",
                confidence_tier: "HIGH",
                category: "DINING",
              },
            ],
          };
        case "get_statement_review_statements__statement_id__review_get":
        case "get_statement_for_review_statements__statement_id__review_get":
          return {
            id: "stmt-1",
            account_id: "acc-1",
            currency: "SGD",
            period_start: "2026-05-01",
            period_end: "2026-05-31",
            opening_balance: "1000.00",
            closing_balance: "1200.00",
            source_result_digest: "a".repeat(64),
            source_missing_facts: ["statement_currency"],
            source_envelope_reviewable: true,
            reviewed_envelope: { id: "env-1" },
            balance_validation_result: {
              opening_match: true,
              closing_match: true,
              calculated_closing: "1200.00",
              opening_delta: "0.00",
              closing_delta: "0.00",
            },
            transactions: [],
          };
        case "list_pending_review_statements_statements_pending_review_get":
        case "list_pending_review_statements_pending_review_get":
          return { items: [{ id: "stmt-1" }], total: 1 };
        case "get_review_conflicts_review_conflicts__statement_id__get":
          return { duplicate_candidates: [], transfer_pair_candidates: [], resolved: true };
        case "list_accounts_accounts_get":
          return {
            items: [{ id: "acc-1", name: "DBS Savings", type: "ASSET", currency: "SGD", is_active: true }],
            total: 1,
          };
        case "list_processing_pending_accounts_processing_pending_get":
          return { items: [] };
        case "reconciliation_stats_reconciliation_stats_get":
          return {
            total_transactions: 10,
            matched_transactions: 10,
            unmatched_transactions: 0,
            pending_review: 0,
            auto_accepted: 10,
            match_rate: 100,
          };
        case "list_ai_suggestions_ai_suggestions_get":
          return { items: [], total: 0 };
        case "get_data_quality_health_reports_data_quality_get":
          return {
            score: 98,
            grade: "A_AUDIT_READY",
            as_of_date: "2026-05-31",
            currency: "SGD",
            equation_invariant: {
              is_healthy: true,
              name: "Accounting Equation Balance",
              summary: "Balance Sheet is strictly balanced (Assets = Liabilities + Equity)",
              detail: "No action required.",
              delta: "0.00",
            },
            temporal_continuity_invariant: {
              is_healthy: true,
              name: "Statement Continuity",
              summary: "1 statement(s) verified across consecutive periods",
              detail: "All consecutive statements match without missing periods.",
              delta: "0",
            },
            reconciliation_purity_invariant: {
              is_healthy: true,
              name: "Reconciliation & Debt Clearance Purity",
              summary: "1 reconciliation item(s) verified",
              detail: "Credit card and loan settlements clear liability accounts.",
              delta: "0",
            },
            lineage_anchors_invariant: {
              is_healthy: true,
              name: "Evidence Lineage & Traceability Anchors",
              summary: "Full source-document-to-report lineage verified",
              detail: "Every report line traces directly to verified statement extraction evidence.",
              delta: "0",
            },
            timeline: [
              {
                month: "2026-05",
                statement_count: 1,
                has_gap: false,
                opening_balance: "1000.00",
                closing_balance: "1200.00",
                net_movement: "200.00",
                status: "HEALTHY",
              },
            ],
            action_items: [],
          };
        case "get_correction_loop_replay_metrics_correction_loop_replay_get":
          return {
            holdout_size: 10,
            grounded: 4,
            proportion_before: "0.30000",
            proportion_after: "0.18000",
            reduced: true,
          };
        case "preview_personal_report_package_reports_package_get":
          return {
            readiness: {
              state: "ready",
              label: "Ready",
              blocking_count: 0,
              action_href: "/reports?tab=package",
              blockers: [],
              input_coverage: {
                manifest_decision_count: 3,
                unproven_input_count: 0,
              },
            },
          };
        case "balance_sheet_reports_balance_sheet_get":
          return {
            as_of_date: "2026-05-31",
            currency: "SGD",
            total_assets: "1200.00",
            total_liabilities: "0.00",
            total_equity: "1200.00",
            equation_delta: "0.00",
            is_balanced: true,
            assets: [],
            liabilities: [],
            equity: [],
          };
        case "income_statement_reports_income_statement_get":
          return {
            start_date: "2026-05-01",
            end_date: "2026-05-31",
            currency: "SGD",
            total_income: "500.00",
            total_expenses: "300.00",
            net_income: "200.00",
            income: [],
            expenses: [],
            trends: [],
          };
        case "cash_flow_reports_cash_flow_get":
          return {
            start_date: "2026-05-01",
            end_date: "2026-05-31",
            currency: "SGD",
            opening_cash: "1000.00",
            closing_cash: "1200.00",
            net_cash_flow: "200.00",
            operating: [],
            investing: [],
            financing: [],
            summary: { total_inflows: "500.00", total_outflows: "300.00", net: "200.00" },
          };
        case "get_holdings_portfolio_holdings_get":
          return {
            items: [
              {
                id: "hold-1",
                asset_identifier: "AAPL",
                asset_type: "equity",
                quantity: "10",
                cost_basis: "1500.00",
                market_value: "1800.00",
                unrealized_pnl: "300.00",
                unrealized_pnl_percent: "20.00",
                acquisition_date: "2026-01-15",
                currency: "SGD",
                status: "active",
                account_id: "acc-1",
                account_name: "Brokerage",
              },
            ],
          };
        case "get_portfolio_summary_portfolio_summary_get":
          return {
            currency: "SGD",
            realized_pnl_ytd: "120.00",
            dividend_income_ytd: "45.00",
          };
        case "get_investment_performance_report_schedule_portfolio_performance_report_schedule_get":
          return {
            period_start: "2026-01-01",
            period_end: "2026-05-31",
            as_of_date: "2026-05-31",
            currency: "SGD",
            realized_pnl: "120.00",
            unrealized_pnl: "300.00",
            dividend_income: "45.00",
            xirr: "12.40",
            time_weighted_return: "11.80",
            money_weighted_return: "12.10",
            dividend_yield: "2.50",
            holdings: [],
            data_freshness: {
              latest_price_date: "2026-05-31",
              market_data_provider: "yahoo_finance",
              stale: false,
              stale_holdings: [],
              manual_override_basis: null,
            },
            source_links: ["report_section:investment_performance"],
            notes: ["Cost basis uses FIFO."],
            methodology_notes: ["Cost basis uses FIFO."],
          };
        case "net_worth_allocation_reports_net_worth_allocation_get":
          return {
            as_of_date: "2026-05-31",
            currency: "SGD",
            include_restricted: true,
            total_assets: "3000.00",
            total_liabilities: "0.00",
            net_worth: "3000.00",
            rows: [],
            excluded_holdings: [],
          };
        case "list_valuation_snapshots_assets_valuation_snapshots_get":
          return { items: [] };
        case "get_sector_allocation_portfolio_allocation_sector_get":
        case "get_geography_allocation_portfolio_allocation_geography_get":
        case "get_asset_class_allocation_portfolio_allocation_asset_class_get":
          return [];
        default:
          return { items: [], total: 0 };
      }
    });

    const screens: Array<{
      name: string;
      url: string;
      expectedText: string;
      renderScreen: () => ReactNode;
    }> = [
      {
        name: "Home",
        url: "/?start=2026-05-01&end=2026-05-31&currency=SGD",
        expectedText: "1 statement waiting for review.",
        renderScreen: () => <HomePage />,
      },
      {
        name: "Upload",
        url: "/upload",
        expectedText: "DBS_May_2026.csv",
        renderScreen: () => <UploadPage />,
      },
      {
        name: "Statement",
        url: "/statements/stmt-1",
        expectedText: "Statement details confirmed",
        renderScreen: () => <StatementReviewPage />,
      },
      {
        name: "Audit",
        url: "/audit?tab=health",
        expectedText: "All Book Checks Pass · Audit Ready",
        renderScreen: () => <AuditPage />,
      },
      {
        name: "Reports",
        url: "/reports?start=2026-05-01&end=2026-05-31&currency=SGD",
        expectedText: "Report readiness",
        renderScreen: () => <ReportsPage />,
      },
      {
        name: "Portfolio",
        url: "/portfolio",
        expectedText: "Total Portfolio Value",
        renderScreen: () => <PortfolioPage />,
      },
      {
        name: "Chat",
        url: "/chat",
        expectedText: "Summarize this month",
        renderScreen: () => <ChatPage />,
      },
    ];

    for (const screenCase of screens) {
      setTestUrl(screenCase.url);
      const view = render(screenCase.renderScreen(), { wrapper: createWrapper() });
      await waitFor(() => {
        expect(extractVisibleText(view.container)).toContain(screenCase.expectedText);
      });
      const text = extractVisibleText(view.container);
      expect(text, `${screenCase.name} screen rendered banned jargon`).not.toMatch(bannedJargon);
      view.unmount();
    }
  });
});

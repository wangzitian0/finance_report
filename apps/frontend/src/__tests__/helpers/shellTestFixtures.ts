import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";
import { createElement, type ReactElement, type ReactNode } from "react";
import { expect, vi, type Mock } from "vitest";
import type { ReportFilters } from "@/hooks/useReportFilters";
import type {
  Account,
  InvestmentPerformanceReportSchedule,
  NetWorthTimeSeriesResponse,
  PortfolioHolding,
  ReconciliationStatsResponse,
  WorkflowStatusResponse,
} from "@/lib/types";

type ApiMockFn = Mock;

export const makeFetchMock = (
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
) =>
  vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    text: () => Promise.resolve(typeof body === "string" ? body : JSON.stringify(body)),
    json: () => Promise.resolve(body),
    blob: () => Promise.resolve(body instanceof Blob ? body : new Blob([String(body)])),
    headers: { get: (name: string) => headers[name] ?? headers[name.toLowerCase()] ?? null },
  });

export const makeAccount = (overrides: Partial<Account> = {}): Account => ({
  id: "a1",
  name: "Cash",
  type: "ASSET",
  currency: "SGD",
  is_active: true,
  balance: "1000",
  is_system: false,
  user_id: "u1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  ...overrides,
});

export const makeWorkflowStatus = (
  primary_state: WorkflowStatusResponse["primary_state"] = "needs_action",
  summary = "Confirm the source.",
): WorkflowStatusResponse =>
  ({
    primary_state,
    next_action: { type: "review_required", count: 1, href: "/audit", label: "Review required", summary },
    report_readiness: { state: "none", blocking_count: 0, href: "/reports" },
    event_counts: { unread: 0, action_required: 1, blocked: 0 },
  }) as WorkflowStatusResponse;

export const makeStats = (overrides: Partial<ReconciliationStatsResponse> = {}): ReconciliationStatsResponse => ({
  total_transactions: 100,
  matched_transactions: 80,
  unmatched_transactions: 5,
  pending_review: 3,
  auto_accepted: 70,
  match_rate: 80,
  score_distribution: {},
  ...overrides,
});

export const makeBalanceSheet = (overrides: Record<string, unknown> = {}) => ({
  as_of_date: "2026-03-31",
  currency: "SGD",
  assets: [{ account_id: "acc-cash", name: "DBS Multiplier", type: "ASSET", amount: "12000" }],
  liabilities: [{ account_id: "acc-card", name: "Visa Infinite", type: "LIABILITY", amount: "2000" }],
  equity: [],
  total_assets: "40000",
  total_liabilities: "2000",
  total_equity: "38000",
  equation_delta: "0",
  is_balanced: true,
  ...overrides,
});

export const makeIncomeStatement = (overrides: Record<string, unknown> = {}) => ({
  start_date: "2026-01-01",
  end_date: "2026-03-31",
  currency: "SGD",
  income: [{ account_id: "acc-salary", name: "Base Salary", type: "INCOME", amount: "9000" }],
  expenses: [{ account_id: "acc-rent", name: "Apartment Rent", type: "EXPENSE", amount: "4500" }],
  total_income: "9000",
  total_expenses: "4500",
  net_income: "4500",
  trends: [],
  ...overrides,
});

export const makeCashFlow = (overrides: Record<string, unknown> = {}) => ({
  start_date: "2026-01-01",
  end_date: "2026-03-31",
  currency: "SGD",
  operating: [],
  investing: [],
  financing: [],
  summary: {
    operating_activities: "4500",
    investing_activities: "-3000",
    financing_activities: "0",
    net_cash_flow: "1500",
    beginning_cash: "10000",
    ending_cash: "11500",
  },
  ...overrides,
});

export const makeHolding = (overrides: Partial<PortfolioHolding> = {}): PortfolioHolding => ({
  id: "h1",
  user_id: "u1",
  account_id: "acc1",
  asset_identifier: "AAPL",
  quantity: "10",
  cost_basis: "1500.00",
  market_value: "1800.00",
  unrealized_pnl: "300.00",
  unrealized_pnl_percent: "20.00",
  currency: "SGD",
  native_cost_basis: "1500.00",
  native_currency: "SGD",
  reporting_cost_basis: "1500.00",
  reporting_currency: "SGD",
  acquisition_date: "2025-01-15",
  status: "active",
  account_name: "IBKR",
  ...overrides,
});

export const makePerformanceSchedule = (
  overrides: Record<string, unknown> = {},
): InvestmentPerformanceReportSchedule =>
  ({
    period_start: "2025-01-01",
    period_end: "2025-12-31",
    as_of_date: "2025-12-31",
    currency: "SGD",
    xirr: "10.00",
    time_weighted_return: "8.00",
    money_weighted_return: "9.50",
    dividend_yield: "2.10",
    realized_pnl: "100.00",
    unrealized_pnl: "250.00",
    dividend_income: "45.00",
    holdings: [],
    allocation: [],
    data_freshness: {
      latest_price_date: "2025-03-31",
      market_data_provider: "Manual",
      stale: false,
      stale_holdings: [],
      manual_override_basis: null,
    },
    source_links: [],
    notes: [],
    ...overrides,
  }) as unknown as InvestmentPerformanceReportSchedule;

export const makeReportFilters = (
  overrides: Partial<ReportFilters> = {},
): ReportFilters => ({
  tab: "balance-sheet",
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
  dimensionQuery: "period=1Y&end=2026-05-20",
  ready: true,
  ...overrides,
});

export const createStaleClient = () =>
  new QueryClient({
    defaultOptions: { queries: { staleTime: 60_000, retry: false, refetchOnWindowFocus: false } },
  });

export const clientWrapper = (client: QueryClient) => {
  const Wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client }, children);
  return Wrapper;
};

export const opCalls = (mockedFn: { mock: { calls: unknown[][] } }, op: string) =>
  mockedFn.mock.calls.filter(([id]) => id === op);

export function mockApiMap(
  mockedFn: { mockImplementation: (fn: never) => unknown },
  routes: Record<string, unknown | ((req: { query?: Record<string, unknown>; path?: Record<string, unknown>; body?: unknown }) => unknown)>,
  fallback: unknown = { items: [], total: 0 },
) {
  mockedFn.mockImplementation(((op: string, req?: { query?: Record<string, unknown>; path?: Record<string, unknown>; body?: unknown }) => {
    if (op in routes) {
      const val = routes[op];
      return Promise.resolve(typeof val === "function" ? (val as (r: unknown) => unknown)(req ?? {}) : val);
    }
    return Promise.resolve(typeof fallback === "function" ? (fallback as (o: string, r: unknown) => unknown)(op, req ?? {}) : fallback);
  }) as never);
}

export const makeStatement = (overrides: Record<string, unknown> = {}) => ({
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
  ...overrides,
});

export const makeStatementReview = (overrides: Record<string, unknown> = {}) => ({
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
  ...overrides,
});

export const makeHumanizeScreenRoutes = () => {
  const stmt = makeStatement();
  return {
    get_user_currency_users_me_currency_get: { currency: "SGD" },
    get_workflow_status_endpoint_workflow_status_get: makeWorkflowStatus("needs_action", "1 statement(s) waiting for review"),
    list_workflow_events_endpoint_workflow_events_get: { items: [{ id: "e1", session_id: "s1", event_type: "statement_parsed", severity: "action_required", status: "unread", title: "1 statement(s) waiting for review", summary: "opening_balance_missing", action_href: "/upload", occurred_at: "2026-05-20T10:00:00Z" }], sessions: [], total: 1 },
    suggestions_chat_suggestions_get: { suggestions: ["Summarize this month"], structured_suggestions: [{ basis: "1 statement(s) waiting for review.", confidence_tier: "review_required", source_refs: ["report_readiness"], limitation: "Market data is stale for 1 observed scope(s).", next_action_href: "/upload" }] },
    chat_history_chat_history_get: { sessions: [] },
    list_statements_statements_get: { items: [stmt], total: 1 },
    get_statement_statements__statement_id__get: stmt,
    get_statement_for_review_statements__statement_id__review_get: makeStatementReview(),
    list_pending_review_statements_pending_review_get: { items: [{ id: "stmt-1" }], total: 1 },
    get_review_conflicts_statements__statement_id__conflicts_get: { duplicate_candidates: [], transfer_pair_candidates: [], resolved: true },
    list_accounts_accounts_get: { items: [makeAccount({ id: "acc-1", name: "DBS Savings" })], total: 1 },
    reconciliation_stats_reconciliation_stats_get: makeStats({ total_transactions: 10, matched_transactions: 10, unmatched_transactions: 0, pending_review: 0, auto_accepted: 10, match_rate: 100 }),
    get_data_quality_health_reports_data_quality_get: { score: 98, grade: "A_AUDIT_READY", as_of_date: "2026-05-31", currency: "SGD", equation_invariant: { is_healthy: true, name: "Accounting Equation Balance", summary: "Balanced", detail: "Ok", delta: "0.00" }, temporal_continuity_invariant: { is_healthy: true, name: "Statement Continuity", summary: "1 statement(s) verified", detail: "Ok", delta: "0" }, reconciliation_purity_invariant: { is_healthy: true, name: "Reconciliation Purity", summary: "1 reconciliation item(s) verified", detail: "Ok", delta: "0" }, lineage_anchors_invariant: { is_healthy: true, name: "Evidence Lineage", summary: "Verified", detail: "Ok", delta: "0" }, timeline: [], action_items: [] },
    get_correction_loop_replay_statements_correction_loop_replay_get: { holdout_size: 10, grounded: 4, proportion_before: "0.3", proportion_after: "0.18", reduced: true },
    preview_personal_report_package_reports_package_get: { readiness: { state: "ready", label: "Ready", blocking_count: 0, action_href: "/reports?tab=package", blockers: [], input_coverage: { manifest_decision_count: 3, unproven_input_count: 0 } } },
    balance_sheet_reports_balance_sheet_get: makeBalanceSheet({ total_assets: "1200.00", total_liabilities: "0.00", total_equity: "1200.00", assets: [], liabilities: [] }),
    income_statement_reports_income_statement_get: makeIncomeStatement({ income: [], expenses: [], total_income: "500.00", total_expenses: "300.00", net_income: "200.00" }),
    cash_flow_reports_cash_flow_get: makeCashFlow(),
    get_holdings_portfolio_holdings_get: { items: [makeHolding({ asset_type: "equity" })] },
    get_portfolio_summary_portfolio_summary_get: { currency: "SGD", realized_pnl_ytd: "120.00", dividend_income_ytd: "45.00" },
    get_investment_performance_report_schedule_portfolio_performance_report_schedule_get: makePerformanceSchedule({ holdings: [], data_freshness: { latest_price_date: "2026-05-31", market_data_provider: "yahoo_finance", stale: false, stale_holdings: [], manual_override_basis: null }, source_links: ["report_section:investment_performance"], notes: ["FIFO"], methodology_notes: ["FIFO"] }),
    net_worth_allocation_reports_net_worth_allocation_get: { as_of_date: "2026-05-31", currency: "SGD", include_restricted: true, total_assets: "3000.00", total_liabilities: "0.00", net_worth: "3000.00", rows: [], excluded_holdings: [] },
    get_sector_allocation_portfolio_allocation_sector_get: [],
    get_geography_allocation_portfolio_allocation_geography_get: [],
    get_asset_class_allocation_portfolio_allocation_asset_class_get: [],
  };
};

export const makeStreamRes = (text: string, headers?: HeadersInit): Response =>
  new Response(new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode(text)); c.close(); } }), { headers });

export const CHAT_SUGGESTIONS = {
  suggestions: ["How is cash flow?"],
  structured_suggestions: [{
    basis: "Report package is blocked by one review-required item.",
    confidence_tier: "blocked",
    source_refs: ["workflow.status", "report_package.readiness"],
    limitation: "Review the blocker before relying on this report.",
    next_action_href: "/reports/package",
  }],
};

export const CHAT_EMPTY_HISTORY = {
  sessions: [{ id: "sess-1", title: "Cash flow review", message_count: 0, messages: [] }],
};

export const CHAT_TABLE_HISTORY = {
  sessions: [{
    id: "sess-1", title: "Review", message_count: 2,
    messages: [
      { id: "m1", role: "user", content: "What is my net worth?" },
      { id: "m2", role: "assistant", content: "Summary:\n| Metric | Value |\n|---|---|\n| Cash | **$5,000** |\nThe above analysis is for reference only." },
    ],
  }],
};

export const makeCockpitBs = (as_of_date: string, total_assets: string, extra: Record<string, unknown> = {}) =>
  makeBalanceSheet({
    as_of_date,
    total_assets,
    assets: [
      { account_id: "acc-cash", name: "DBS Multiplier", type: "ASSET", amount: "12000" },
      { account_id: "acc-broker", name: "IBKR Portfolio", type: "ASSET", amount: "28000" },
      { account_id: "acc-proc", name: "Processing", type: "ASSET", amount: "-250" },
      { account_id: "acc-empty", name: "Closed Account", type: "ASSET", amount: "0" },
    ],
    opening_balance_warnings: [{ type: "missing_opening_balance", message: "Record opening balances." }],
    ...extra,
  });

export const COCKPIT_CF = makeCashFlow({
  operating: [{ line_id: "op-1", category: "operating", subcategory: "Salary received", amount: "9000", account_id: "acc-cash", event_count: 3 }],
  investing: [{ line_id: "inv-1", category: "investing", subcategory: "Broker transfer", amount: "-3000", account_id: null, event_count: 1 }],
  financing: [{ line_id: "fin-1", category: "financing", subcategory: "Card repayment", description: "Outflow - DBS Multiplier", amount: "-500", account_id: "acc-cash", event_count: 1 }],
});

export const LLM_PROVIDER = { id: "prov-1", label: "OpenRouter", protocol: "openrouter-compatible" as const, api_base: "https://openrouter.ai/api/v1", has_api_key: true, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" };
export const LLM_MODEL = { id: "openrouter/auto", provider_id: "prov-1", modalities: ["text" as const], is_free: true, input_price_per_mtok: null, output_price_per_mtok: null, supports_reasoning: true };
export const LLM_BINDING = { scene: "advisor.chat", provider_id: "prov-1", model: "openrouter/auto", reasoning: "low", max_tokens: null };

export const mockLlmRoutes = (api: ApiMockFn, overrides: Record<string, unknown> = {}) =>
  mockApiMap(api, {
    list_providers_llm_providers_get: { providers: [LLM_PROVIDER] },
    get_catalog_llm_catalog_get: { models: [LLM_MODEL] },
    get_scenes_llm_scenes_get: { bindings: [LLM_BINDING] },
    put_scenes_llm_scenes_put: { bindings: [] },
    delete_provider_llm_providers__provider_id__delete: undefined,
    create_provider_llm_providers_post: LLM_PROVIDER,
    ...overrides,
  });

export const AI_SETTINGS_DEFAULT = {
  enable_ai_reconciliation: true,
  enable_ai_classification: false,
  auto_accept_ai_suggestions: true,
  auto_accept_ai_suggestions_active: false,
};

export const mockAiSettingsRoutes = (api: ApiMockFn, getVal = AI_SETTINGS_DEFAULT, patchVal: unknown = AI_SETTINGS_DEFAULT) =>
  mockApiMap(api, {
    get_current_user_settings_users_me_settings_get: getVal,
    patch_current_user_settings_users_me_settings_patch: patchVal,
  });

export const HOME_BS = makeBalanceSheet({
  assets: [{ account_id: "a1", name: "Cash", amount: "5000" }],
  liabilities: [],
  total_assets: "5000",
  total_liabilities: "1000",
  total_equity: "4000",
  currency: "USD",
});

export const makeHomeRoutes = (extra: Record<string, unknown> = {}) => ({
  balance_sheet_reports_balance_sheet_get: (r: { query?: Record<string, unknown> }) => (r.query?.include_restricted === false ? { ...HOME_BS, total_assets: "2500", total_equity: "1500" } : HOME_BS),
  income_statement_reports_income_statement_get: makeIncomeStatement({ currency: "USD", total_income: "3500", total_expenses: "1200", net_income: "2300" }),
  cash_flow_reports_cash_flow_get: makeCashFlow({ currency: "USD", summary: { operating_activities: "2300", investing_activities: "0", financing_activities: "0", net_cash_flow: "2300", beginning_cash: "0", ending_cash: "2300" } }),
  reconciliation_stats_reconciliation_stats_get: makeStats({ total_transactions: 20, matched_transactions: 16, unmatched_transactions: 4, pending_review: 2, auto_accepted: 4 }),
  list_statements_statements_get: { items: [{ id: "s1", status: "approved" }], total: 1 },
  list_processing_pending_reconciliation_transfers_pending_get: { items: [], total: 0 },
  suggestions_chat_suggestions_get: { suggestions: [], structured_suggestions: [] },
  get_available_currencies_reports_currencies_get: ["SGD", "USD"],
  get_base_currency_users_me_settings_base_currency_get: { base_currency: "USD" },
  get_workflow_status_endpoint_workflow_status_get: makeWorkflowStatus("ready", "Reports are ready."),
  ...extra,
});

export const makeJournalEntry = (id: string, status: string, memo: string, amount = 200, source_type = "manual") => ({
  id, memo, entry_date: "2026-01-01", status, source_type, created_at: "2026-01-01T00:00:00Z",
  lines: [
    { id: `${id}-1`, account_id: "a1", direction: "DEBIT", amount, currency: "SGD", description: "d" },
    { id: `${id}-2`, account_id: "a2", direction: "CREDIT", amount, currency: "SGD", description: "c" },
  ],
});

export const JOURNAL_ACCOUNTS = [
  { id: "a1", name: "Cash", code: "1000", type: "ASSET", currency: "SGD", is_active: true, balance: 0 },
  { id: "a2", name: "Revenue", code: "4000", type: "INCOME", currency: "SGD", is_active: true, balance: 0 },
];

export const JOURNAL_FX_ACCOUNTS = [
  { id: "a1", name: "USD Bank", code: "1010", type: "ASSET", currency: "USD", is_active: true, balance: 0 },
  { id: "a2", name: "Owner Equity", code: "3000", type: "EQUITY", currency: "SGD", is_active: true, balance: 0 },
];

export const OPENING_ACCOUNTS = [
  makeAccount({ id: "a1", name: "Cash", type: "ASSET" }),
  makeAccount({ id: "a2", name: "Credit Card", type: "LIABILITY" }),
  makeAccount({ id: "a3", name: "Salary", type: "INCOME" }),
  makeAccount({ id: "a4", name: "Closed", type: "ASSET", is_active: false }),
];

export const TWO_NET_WORTH_POINTS: NetWorthTimeSeriesResponse = {
  currency: "SGD",
  granularity: "daily",
  points: [
    { date: "2026-05-01", total_assets: "1000.00", total_liabilities: "100.00", net_worth: "900.00", currency: "SGD" },
    { date: "2026-05-02", total_assets: "1100.00", total_liabilities: "100.00", net_worth: "1000.00", currency: "SGD" },
  ],
};

export const makePortfolioTrustRoutes = () => ({
  get_holdings_portfolio_holdings_get: { items: [makeHolding()], total: 1, warnings: [] },
  get_portfolio_summary_portfolio_summary_get: { total_market_value: "1800.00", total_cost_basis: "1500.00", total_unrealized_pnl: "300.00", total_unrealized_pnl_percent: "20.00", total_realized_pnl: "0.00", total_realized_pnl_percent: "0.00", net_pnl: "300.00", net_pnl_percent: "20.00", holdings_count: 1, active_positions_count: 1, disposed_positions_count: 0, currency: "SGD", realized_pnl_ytd: "0.00", dividend_income_ytd: "200.00" },
  get_investment_performance_report_schedule_portfolio_performance_report_schedule_get: makePerformanceSchedule({ xirr: null, time_weighted_return: null, money_weighted_return: null, dividend_yield: null, realized_pnl: "0.00", unrealized_pnl: "300.00", dividend_income: "200.00" }),
  net_worth_allocation_reports_net_worth_allocation_get: {
    as_of_date: "2025-12-31", currency: "SGD", include_restricted: true, total_assets: "1121190.40", total_liabilities: "647900.00", net_worth: "473290.40", excluded_holdings: [],
    rows: [
      { asset_class: "real_estate", liquidity_class: "illiquid", source_currency: "SGD", value: "1050000.00", percentage_of_net_worth: "221.9", source_line_count: 1, source_lines: [{ source_type: "manual_valuation", source_id: "val-prop-1", label: "HDB Valuation Report 2025-Q1 Long Identifier Without Spaces", value: "1050000.00" }] },
      { asset_class: "liability", liquidity_class: "liability", source_currency: "SGD", value: "-647900.00", percentage_of_net_worth: "-136.9", source_line_count: 1, source_lines: [{ source_type: "manual_valuation", source_id: "val-loan-1", label: "Mortgage", value: "-647900.00" }] },
    ],
  },
});

export function makePwaPromptEvent(outcome: "accepted" | "dismissed" = "accepted") {
  const event = new Event("beforeinstallprompt", { cancelable: true }) as Event & { prompt: ReturnType<typeof vi.fn>; userChoice: Promise<{ outcome: string; platform: string }> };
  Object.defineProperties(event, {
    preventDefault: { value: vi.fn(), configurable: true },
    prompt: { value: vi.fn().mockResolvedValue(undefined), configurable: true },
    userChoice: { value: Promise.resolve({ outcome, platform: "web" }), configurable: true },
  });
  return event;
}

export function mockPwaDisplayMode(matches: boolean) {
  const listeners = new Set<(e: Event) => void>();
  const mediaQuery = {
    matches,
    media: "(display-mode: standalone)",
    addEventListener: vi.fn((_: string, fn: (e: Event) => void) => listeners.add(fn)),
    removeEventListener: vi.fn((_: string, fn: (e: Event) => void) => listeners.delete(fn)),
  } as unknown as MediaQueryList;
  Object.defineProperty(window, "matchMedia", { value: vi.fn(() => mediaQuery), configurable: true });
  return {
    mediaQuery,
    setMatches(next: boolean) {
      Object.defineProperty(mediaQuery, "matches", { value: next, configurable: true });
      listeners.forEach((fn) => fn(new Event("change")));
    },
  };
}

export function setPwaNavigator(props: { maxTouchPoints?: number; platform?: string; standalone?: boolean; userAgent?: string }) {
  const defs: PropertyDescriptorMap = {};
  for (const [k, v] of Object.entries(props)) {
    if (v !== undefined) defs[k] = { value: v, configurable: true };
  }
  Object.defineProperties(window.navigator, defs);
}

export function discoverPageRoutes(dir: string, segments: string[] = []): string[] {
  const found: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      const isGroup = entry.name.startsWith("(") && entry.name.endsWith(")");
      found.push(...discoverPageRoutes(path.join(dir, entry.name), isGroup ? segments : [...segments, entry.name]));
    } else if (entry.name === "page.tsx") {
      found.push("/" + segments.join("/"));
    }
  }
  return found;
}

export const BANNED_JARGON_RE = /\b(invariant|invariants|rollforward|source envelope|reviewed disposition|economic intent|held-out|leakage|authority decisions|unproven inputs|unproven package input|scene bindings)\b|\b[a-z]+_[a-z_]+\b|\(s\)/i;

export function visibleText(el: HTMLElement): string {
  const clone = el.cloneNode(true) as HTMLElement;
  clone.querySelectorAll("[aria-hidden='true'], .hidden").forEach((n) => n.remove());
  return clone.textContent ?? "";
}

export const HUMANIZE_SUGGESTIONS = [
  { basis: "1 statement(s) waiting for review in report_readiness.", confidence_tier: "review_required" as const, source_refs: ["report_readiness", "authority_coverage", "market_data", "cash_flow"], limitation: "Market data is stale for 1 observed scope(s).", next_action_href: "/review" },
  { basis: "Ledger totals are reconciled.", confidence_tier: "deterministic" as const, source_refs: ["workflow.status", "reconciliation"], limitation: "Posted entries only.", next_action_href: "/reports" },
];

export const HUMANIZE_BRIEF_LABELS = ["Review Required", "Report Readiness", "Authority Coverage", "Market Data", "Cash Flow", "1 statement waiting for review in report readiness."];

export const HUMANIZE_PKG_CONTRACT = {
  package_id: "personal-financial-report-package",
  version: "1.0.0",
  period_semantics: { start_date: "", end_date: "", as_of_date: "" },
  supported_frameworks: [],
  selected_framework_id: null,
  sections: [],
  export_contract: { formats: ["json"], csv_columns: [] },
};

export const HUMANIZE_ACCOUNTS_ROUTES = {
  get_opening_balance_readiness_status_accounts_opening_balance_readiness_get: { needs_opening_balance: false },
  list_accounts_accounts_get: {
    items: [
      makeAccount({ id: "a1", name: "Brokerage Custody", code: "AUTO-ASSET", balance: "1500" }),
      makeAccount({ id: "a2", name: "Processing", code: "SYS-PROCESSING", balance: "0", is_system: true }),
      makeAccount({ id: "a3", name: "Operating Cash", code: "1001", balance: "2500" }),
    ],
    total: 3,
  },
};

export const OTEL_CFG = { endpoint: "https://otel.zitian.party/v1/traces", environment: "staging", serviceVersion: "abc123" };

export const fakeOtelProvider = () => {
  const recordException = vi.fn();
  const setAttribute = vi.fn();
  const end = vi.fn();
  return { recordException, setAttribute, end, provider: { getTracer: () => ({ startSpan: () => ({ setAttribute, recordException, end }) }) } };
};

export function withDefinedProps(defs: [object, string, PropertyDescriptor][], fn: () => void) {
  const orig = defs.map(([t, k]) => [t, k, Object.getOwnPropertyDescriptor(t, k)] as const);
  try {
    for (const [t, k, d] of defs) Object.defineProperty(t, k, { configurable: true, ...d });
    fn();
  } finally {
    for (const [t, k, d] of orig) if (d) Object.defineProperty(t, k, d);
  }
}

export const makeCoverageRoutes = (getStart: () => string | null, getLatest: () => string | null = () => null) => ({
  report_coverage_reports_coverage_get: (r: { query?: Record<string, unknown> }) => ({
    as_of_date: r.query?.as_of_date,
    coverage_start: getStart(),
    limiting_accounts: getStart() ? ["OCBC Bank"] : [],
    latest_statement_end: getLatest(),
  }),
  balance_sheet_reports_balance_sheet_get: (r: { query?: Record<string, unknown> }) =>
    makeBalanceSheet({ as_of_date: String(r.query?.as_of_date), total_assets: r.query?.as_of_date === getStart() ? "3500" : "5000", total_liabilities: "1000" }),
  income_statement_reports_income_statement_get: makeIncomeStatement({ total_income: "3000", total_expenses: "1500", net_income: "1500" }),
  cash_flow_reports_cash_flow_get: makeCashFlow({ summary: { operating_activities: "1500", investing_activities: "0", financing_activities: "0", net_cash_flow: "1500", beginning_cash: "0", ending_cash: "1500" } }),
  reconciliation_stats_reconciliation_stats_get: makeStats({ total_transactions: 5, matched_transactions: 5, unmatched_transactions: 0, pending_review: 0, auto_accepted: 5, match_rate: 100 }),
  get_available_currencies_reports_currencies_get: ["SGD"],
  get_base_currency_users_me_settings_base_currency_get: { base_currency: "SGD" },
});

export const REVIEW_PENDING_ROUTES = (resolveReview: (fn: (v: unknown) => void) => void) => ({
  get_statement_statements__statement_id__get: makeStatement({ id: "stmt-2765", original_filename: "dbs.pdf", period_start: "2026-01-01", period_end: "2026-01-31", confidence_score: undefined, balance_validated: undefined }),
  get_statement_for_review_statements__statement_id__review_get: () => new Promise((r) => { resolveReview(r); }),
  list_pending_review_statements_pending_review_get: { items: [{ id: "stmt-2765" }], total: 1 },
  get_review_conflicts_statements__statement_id__conflicts_get: { duplicates: [], transfer_pairs: [] },
});

export const REVIEW_RESOLVED_PAYLOAD = makeStatementReview({
  id: "stmt-2765",
  period_start: "2026-01-01",
  period_end: "2026-01-31",
  source_result_digest: undefined,
  source_missing_facts: [],
  source_envelope_reviewable: false,
  reviewed_envelope: null,
  balance_validation_result: { opening_balance: "1000.00", closing_balance: "1200.00", calculated_closing: "1200.00", opening_delta: "0.00", closing_delta: "0.00", opening_match: true, closing_match: true },
});

export const OVERFLOW_BS = makeBalanceSheet({
  as_of_date: "2026-02-01",
  assets: [{ account_id: "asset-neg", name: "Margin Cash Account With Very Long Label", type: "ASSET", parent_id: null, amount: "-1250.00", provenance: "imported" }],
  liabilities: [{ account_id: "liab-1", name: "Credit Card Payable", type: "LIABILITY", parent_id: null, amount: "450.00", provenance: "imported" }],
  equity: [{ account_id: "eq-1", name: "Retained Earnings", type: "EQUITY", parent_id: null, amount: "-1700.00", provenance: "derived" }],
  total_assets: "-1250.00", total_liabilities: "450.00", total_equity: "-1700.00",
});

export const btn = (name: string | RegExp) => screen.getByRole("button", { name });
export const lnk = (name: string | RegExp) => screen.getByRole("link", { name });
export const clkBtn = (name: string | RegExp) => fireEvent.click(btn(name));
export const clkTxt = (text: string | RegExp) => fireEvent.click(screen.getByText(text));
export const clkLbl = (label: string | RegExp) => fireEvent.click(screen.getByLabelText(label));
export const chgLbl = (label: string | RegExp, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
export const chgPh = (ph: string | RegExp, value: string) => fireEvent.change(screen.getByPlaceholderText(ph), { target: { value } });
export const alertEl = () => screen.findByRole("alert");
export const dlgEl = (name?: string | RegExp) => (name ? screen.findByRole("dialog", { name }) : screen.findByRole("dialog"));
export const hasTxts = (...ts: (string | RegExp)[]) => { for (const t of ts) expect(screen.getByText(t)).toBeInTheDocument(); };
export const noTxt = (t: string | RegExp) => expect(screen.queryByText(t)).toBeNull();
export const chkLnk = (n: string | RegExp, href: string) => expect(lnk(n)).toHaveAttribute("href", href);
export const waitOp = (api: unknown, op: string, req?: unknown) =>
  waitFor(() => req !== undefined ? expect(api).toHaveBeenCalledWith(op, req) : expect(api).toHaveBeenCalledWith(op));
export const findAlert = async (txt: string | RegExp) => expect(await screen.findByRole("alert")).toHaveTextContent(txt);

export const HUMANIZE_SCREENS = [
  ["Home", "/?start=2026-05-01&end=2026-05-31&currency=SGD", "1 statement waiting for review."],
  ["Upload", "/upload", "DBS_May_2026.csv"],
  ["Statement", "/statements/stmt-1", "Statement details confirmed"],
  ["Audit", "/audit?tab=health", "All Book Checks Pass · Audit Ready"],
  ["Reports", "/reports?start=2026-05-01&end=2026-05-31&currency=SGD", "Report readiness"],
  ["Portfolio", "/portfolio", "Total Portfolio Value"],
  ["Chat", "/chat", "Summarize this month"],
] as const;

export const OTEL_URL_HOOK_CASES: Array<[string | Request | RequestInit | { url?: string }, string, string]> = [
  ["https://x.com/p?s=1", "http.url", "https://x.com/p"],
  [{ url: "https://x.com/q?a=b#c" }, "http.target", "https://x.com/q"],
  [{}, "", ""],
];

export const COCKPIT_DRILL_CASES = [
  [null, null, "acc-broker", undefined],
  ["Income", "View source transactions for Base Salary", "acc-salary", "2026-01-01"],
  ["Cash", "View source transactions for Outflow - DBS Multiplier", "acc-cash", "2026-01-01"],
] as const;

export const OPS = {
  BS: "balance_sheet_reports_balance_sheet_get",
  IS: "income_statement_reports_income_statement_get",
  CF: "cash_flow_reports_cash_flow_get",
  LIN: "account_lineage_reports_account_lineage_get",
  NW_TS: "net_worth_timeseries_reports_net_worth_timeseries_get",
  COV: "report_coverage_reports_coverage_get",
  CURR: "get_available_currencies_reports_currencies_get",
  BASE_CURR: "get_base_currency_users_me_settings_base_currency_get",
  PUT_BASE_CURR: "update_base_currency_users_me_settings_base_currency_put",
  WF: "get_workflow_status_endpoint_workflow_status_get",
  STMT_LIST: "list_statements_statements_get",
  STMT_REV: "get_statement_for_review_statements__statement_id__review_get",
  REC_STATS: "reconciliation_stats_reconciliation_stats_get",
  REC_PEND: "list_processing_pending_reconciliation_transfers_pending_get",
  REC_UNM: "list_unmatched_reconciliation_unmatched_get",
  SUG: "suggestions_chat_suggestions_get",
  CHAT_HIST: "chat_history_chat_history_get",
  CHAT_DEL: "delete_session_chat_sessions__session_id__delete",
  CHAT_POST: "chat_message_chat_post",
  LLM_PROV_LIST: "list_providers_llm_providers_get",
  LLM_CAT: "get_catalog_llm_catalog_get",
  LLM_SCENES_GET: "get_scenes_llm_scenes_get",
  LLM_SCENES_PUT: "put_scenes_llm_scenes_put",
  LLM_PROV_DEL: "delete_provider_llm_providers__provider_id__delete",
  LLM_PROV_ADD: "create_provider_llm_providers_post",
  AI_GET: "get_current_user_settings_users_me_settings_get",
  AI_PATCH: "patch_current_user_settings_users_me_settings_patch",
  LOGOUT: "logout_auth_logout_post",
  LOGIN: "login_auth_login_post",
  REG: "register_auth_register_post",
  ACC_LIST: "list_accounts_accounts_get",
  ACC_ADD: "create_account_accounts_post",
  ACC_UPD: "update_account_accounts__account_id__put",
  ACC_DEL: "delete_account_accounts__account_id__delete",
  OPEN_BAL: "post_opening_balances_accounts_opening_balances_post",
  JE_LIST: "list_journal_entries_journal_entries_get",
  JE_ADD: "create_entry_journal_entries_post",
  JE_POST: "post_entry_journal_entries__entry_id__postings_post",
  JE_DEL: "delete_journal_entry_journal_entries__entry_id__delete",
  JE_VOID: "void_entry_journal_entries__entry_id__voidings_post",
  ME: "get_me_auth_me_get",
  DIV: "get_holding_dividends_portfolio__ticker__dividends_get",
  UPL: "upload_statement_statements_post",
  EXP: "export_report_reports_exports_get",
} as const;

export const linkMock = {
  default: ({ href, children, scroll: _s, ...p }: { href: string; children: ReactNode; scroll?: boolean }) =>
    createElement("a", { href, ...p }, children),
};

export const metricEl = (id: string, label: string) =>
  within(screen.getByTestId(id)).getByText(label).nextElementSibling;

export const COCKPIT_DEFAULT_ROUTES = {
  [OPS.BS]: (r: { query?: Record<string, unknown> }) => r.query?.as_of_date === "2025-12-31" ? makeCockpitBs("2025-12-31", "32000") : makeCockpitBs("2026-03-31", "40000"),
  [OPS.IS]: makeIncomeStatement(),
  [OPS.CF]: COCKPIT_CF,
  [OPS.LIN]: () => new Promise(() => undefined),
};

export const COCKPIT_EMPTY_ROUTES = {
  [OPS.BS]: makeCockpitBs("2026-03-31", "0", { assets: [], liabilities: [] }),
  [OPS.IS]: makeIncomeStatement({ income: [], expenses: [], total_income: "0", total_expenses: "0", net_income: "0" }),
  [OPS.CF]: makeCashFlow(),
};

export const COCKPIT_VAL_BS = makeCockpitBs("2026-03-31", "82000", {
  assets: [
    { account_id: "val-cpf-1", name: "Valuation: CPF", type: "ASSET", amount: "50000", allocation_source_type: "manual_valuation" },
    { account_id: "acc-cash", name: "DBS Multiplier", type: "ASSET", amount: "12000", allocation_source_type: "ledger_account" },
  ],
});

export const COCKPIT_VAL_ROUTES = {
  [OPS.BS]: COCKPIT_VAL_BS,
  [OPS.IS]: makeIncomeStatement(),
  [OPS.CF]: COCKPIT_CF,
};

export const COCKPIT_METRICS = [
  ["cockpit-card-balance-sheet", "Net worth", "SGD 38,000"],
  ["cockpit-card-balance-sheet", "Change in period", "+SGD 8,000"],
  ["cockpit-card-income-statement", "Savings rate", "50%"],
  ["cockpit-card-cash-flow", "Net change", "+SGD 1,500"],
] as const;

export async function verifyScreenNoJargon(
  api: ApiMockFn,
  url: string,
  expected: string,
  el: ReactElement,
  setUrl: (u: string) => void,
  name: string,
) {
  mockApiMap(api, makeHumanizeScreenRoutes());
  setUrl(url);
  const v = render(el);
  await waitFor(() => expect(visibleText(v.container)).toContain(expected), { timeout: 1500 });
  expect(visibleText(v.container), name).not.toMatch(BANNED_JARGON_RE);
  v.unmount();
}

export const OTEL_CLEAN_ATTRS = { "http.url": "https://x.com/p", "document.url": "https://x.com/d", "http.target": 8080, "ok.flag": true };
export const OTEL_RESOLVE_CASES = [
  [{}, null],
  [{ NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT: "   " }, null],
  [{ NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT: "https://o/v1/traces" }, { endpoint: "https://o/v1/traces", environment: "unknown", serviceVersion: "unknown" }],
] as const;
export const OTEL_SPAN_KEYS = ["http.url", "http.target", "url.full", "document.url"] as const;
export const OTEL_REDACT_CASES = [
  [new Error("user a@b.com owes $1,234"), "Error"],
  [{}, "Error"],
  [{ name: "TypeError" }, "TypeError"],
] as const;
export const OTEL_DOC_CASES: Array<{ defs: [object, string, PropertyDescriptor][]; expected?: string }> = [
  { defs: [[document, "documentURI", { get: () => "https://x.com/p?t=1#h" }]], expected: "https://x.com/p" },
  { defs: [[document, "documentURI", { get: () => "" }], [window, "location", { get: () => ({ href: "https://x.com/h?u=1" }) }]], expected: "https://x.com/h" },
  { defs: [[document, "documentURI", { get() { throw new Error("x"); } }], [window, "location", { get() { throw new Error("x"); } }]] },
];

export const OTEL_ERR_CASES: Array<[string, unknown, string?]> = [
  ["error", { error: new Error("s") }, "Error"],
  ["unhandledrejection", { reason: "s" }],
  ["error", { error: undefined }],
  ["unhandledrejection", { reason: new TypeError("b") }, "TypeError"],
];

export async function checkHumanizeBrief() {
  const c0 = screen.getByTestId("advisor-brief-card-0");
  for (const t of HUMANIZE_BRIEF_LABELS) expect(within(c0).getByText(t)).toBeInTheDocument();
  expect(within(c0).queryByText("review_required")).toBeNull();
}

export function checkHumanizePkg(c: HTMLElement) {
  expect(screen.getByText("Personal Financial Report Package")).toBeInTheDocument();
  expect(screen.getByRole("status", { name: "Loading report package" })).toHaveAttribute("aria-busy", "true");
  expect(c.querySelectorAll("[data-testid='skeleton-block']").length).toBeGreaterThanOrEqual(10);
}

export async function checkHumanizeAccounts() {
  await waitFor(() => expect(screen.getByText("Brokerage Custody")).toBeInTheDocument());
  hasTxts("Auto-created", "System clearing", "1001");
  noTxt("AUTO-ASSET");
}

export const WORKSPACE_TAB_1 = { id: "tab-1", label: "Dashboard", href: "/dashboard", icon: "LayoutDashboard" };
export const WORKSPACE_TAB_2 = { id: "tab-2", label: "Accounts", href: "/settings?tab=accounts", icon: "Landmark" };
export const SIDEBAR_EMPTY_WS = { tabs: [], activeTabId: null };
export const SIDEBAR_TWO_TABS_WS = { tabs: [WORKSPACE_TAB_1, WORKSPACE_TAB_2], activeTabId: "tab-1" };

export const listOfAccounts = (items: Account[]) => ({ items, total: items.length });

export const mockAccountsStd = (api: ApiMockFn, extra: Record<string, unknown> = {}) =>
  mockApiMap(api, {
    get_opening_balance_readiness_status_accounts_opening_balance_readiness_get: { needs_opening_balance: false },
    [OPS.ACC_LIST]: listOfAccounts([makeAccount({ id: "a1", name: "Cash" })]),
    [OPS.ACC_DEL]: undefined,
    ...extra,
  });

export const resetPwaDefaults = () => {
  localStorage.clear();
  setPwaNavigator({ maxTouchPoints: 0, platform: "Linux x86_64", standalone: false, userAgent: "Mozilla/5.0" });
};

export const makePwaPromptState = (overrides: Record<string, unknown> = {}) => ({
  isInstalled: false,
  promptKind: "native" as const,
  canPrompt: true,
  promptInstall: vi.fn().mockResolvedValue(undefined),
  dismissPrompt: vi.fn(),
  ...overrides,
});

export const ROUTE_RETIRED_UPLOAD = {
  "/notifications": "/upload", "/processing": "/upload", "/accounts/processing": "/upload",
  "/statements/[id]/review": "/statements/[id]", "/events": "/upload", "/review": "/upload",
};

export const ROUTE_AUDIT_REDIRECTS = [
  ["/attention", "/attention", "/audit?tab=needs-you"],
  ["/confidence", "/confidence", "/audit?tab=needs-you"],
  ["/review/ai-suggestions", "/review/ai-suggestions", "/audit?tab=needs-you"],
  ["/review/run/[runId]", "/review/run/:runId", "/audit?run_id=:runId"],
] as const;

export const ROUTE_QUERY_REDIRECTS = [
  ["/reconciliation/unmatched", "/reconciliation", { tab: "unmatched" }],
  ["/reconciliation/review-queue", "/reconciliation", { tab: "review-queue" }],
  ["/portfolio/prices", "/portfolio", { panel: "prices" }],
  ["/portfolio/evidence", "/portfolio", { panel: "evidence" }],
  ["/portfolio/AAPL", "/portfolio", { ticker: "AAPL" }],
  ["/accounts", "/settings", { tab: "accounts" }],
  ["/reconciliation/unmatched?statement_id=s1&return_to=%2Fstatements%2Fs1", "/reconciliation", { tab: "unmatched", statement_id: "s1", return_to: "/statements/s1" }],
  ["/portfolio/evidence?source_class=property", "/portfolio", { panel: "evidence", source_class: "property" }],
] as const;

export const ROUTE_LEGACY_DELETED = [
  "/reconciliation/unmatched", "/reconciliation/review-queue", "/portfolio/[ticker]",
  "/portfolio/prices", "/portfolio/evidence", "/accounts",
] as const;

export const HOME_EXPECTED_OPS = [
  OPS.BS, OPS.BS, OPS.CF, OPS.CURR, OPS.BASE_CURR, OPS.WF, OPS.IS,
  OPS.REC_PEND, OPS.STMT_LIST, OPS.REC_UNM, OPS.REC_STATS, OPS.COV, OPS.SUG,
].sort();

export const homeCallKeys = (api: ApiMockFn) =>
  api.mock.calls.map(([op, req]) => {
    const { signal: _s, ...rest } = ((req ?? {}) as Record<string, unknown>);
    return `${String(op)} ${JSON.stringify(rest)}`;
  });

export const OPENING_SUGGEST_CASES = [["2024-03-01", "2024-02-29"], ["2026-01-01", "2025-12-31"]] as const;

export const OPENING_VALIDATION_CASES = [
  ["2026-03-01", "2026-03-01", "100.00", "Opening balances must be dated before the first report period starts."],
  ["", "2026-01-01", "", "Enter a starting balance for at least one account."],
  ["", "", "100", "Enter the as-of date for these opening balances."],
  ["", "2026-01-01", "1.234", "Balances must be positive amounts with at most two decimal places."],
] as const;

export const PORTFOLIO_LINK_CASES = [
  ["price_source:override:AAPL:1581301e-269d-4847-8fb7-fd21763d1f0d:2025-03-31", "Manual price · AAPL (2025-03-31)"],
  ["price_source:stock_price:NVDA:5ec4d3e2-256c-4c11-8de1-40f74d1802c1:2026-10-26", "Market price · NVDA (2026-10-26)"],
  ["price_source:atomic_position:STI.SI:e8b2bbe5-85bc-4796-9d10-450c1b400ead:2025-03-31", "Position snapshot · STI.SI (2025-03-31)"],
  ["statement:9f38b1a2-1111-4222-8333-444455556666", "Statement record"],
  ["report_section:investment_performance", "Report section · Investment Performance"],
] as const;

export const PORTFOLIO_SCHEDULE_PROPS = {
  holdings: [{ asset_identifier: "AAPL", quantity: "10", cost_basis: "1000.00", market_value: "1250.00", unrealized_pnl: "250.00", realized_pnl: "100.00", dividend_income: "45.00", currency: "SGD" }],
  data_freshness: { latest_price_date: "2025-03-31", market_data_provider: "Interactive Brokers, yahoo_finance", stale: false, stale_holdings: [], manual_override_basis: "NVDA:2025-03-31" },
  source_links: [
    "price_source:override:AAPL:1581301e-269d-4847-8fb7-fd21763d1f0d:2025-03-31",
    "price_source:stock_price:NVDA:5ec4d3e2-256c-4c11-8de1-40f74d1802c1:2026-10-26",
    "statement:9f38b1a2-1111-4222-8333-444455556666",
    "report_section:investment_performance",
  ],
};

export const AI_NOTE_CASES = [
  [true, true, false, true],
  [true, false, false, false],
  [false, true, false, false],
  [true, true, true, false],
] as const;

export const ACTION_CONFLICT_ROUTES = {
  [OPS.REC_STATS]: makeStats({ total_transactions: 26, matched_transactions: 25, unmatched_transactions: 1, pending_review: 0, auto_accepted: 25, match_rate: 96 }),
  [OPS.STMT_LIST]: { items: [{ id: "s-oct", status: "parsed", original_filename: "october.csv", confidence_score: 80, balance_validated: true }, { id: "s-ibkr", status: "parsed", original_filename: "ibkr.csv", confidence_score: 20, balance_validated: true }], total: 2 },
  [OPS.REC_PEND]: { items: [], total: 0 },
  [OPS.REC_UNM]: { items: [{ id: "t1", description: "PayNow Transfer REF 4471" }], total: 1 },
  [OPS.WF]: makeWorkflowStatus("blocked"),
};

export const ACTION_CLEAR_ROUTES = {
  [OPS.REC_STATS]: makeStats({ total_transactions: 10, matched_transactions: 10, unmatched_transactions: 0, pending_review: 0, auto_accepted: 10, match_rate: 100 }),
  [OPS.STMT_LIST]: { items: [], total: 0 },
  [OPS.REC_PEND]: { items: [], total: 0 },
  [OPS.REC_UNM]: { items: [], total: 0 },
};

export const API_STATUS_CASES = [
  [401, JSON.stringify({ detail: "Not authenticated" }), "Authentication required", "/login"],
  [500, JSON.stringify({ detail: "Internal error" }), "Internal error", ""],
  [400, "plain text", "plain text", ""],
  [422, "false", "false", ""],
  [404, "", "Request failed with 404", ""],
] as const;

export const API_DOWNLOAD_CASES = [
  ["attachment; filename*=UTF-8''report%202026.csv", "report 2026.csv"],
  ["attachment; filename*=UTF-8''%E0%A4%A", "%E0%A4%A"],
  ["attachment; filename=plain_report.csv", "plain_report.csv"],
  ["attachment; other=1", null],
  [null, null],
] as const;

export const CASH_FLOW_BRIDGE_PAYLOAD = makeCashFlow({
  summary: { operating_activities: "0.00", investing_activities: "0.00", financing_activities: "0.00", net_cash_flow: "-1250.00", beginning_cash: "5000.00", ending_cash: "3750.00" },
  cash_bridge: { classified_activity: "0.00", unclassified_cash: "-1250.00", fx_effect: "0.00", cash_delta: "-1250.00", discrepancy: "0.00", reconciles: true },
  proof_state: "unproven",
  proof_reasons: ["cash_event_classification_ambiguous"],
});

export const DESIGN_SSOT_MARKERS = [
  "## 4. Design Tokens", "### Token Families", "### Page-Local Visual Decisions", "Login uses the accent gradient",
  "Dashboard cards and chart panels", "**Border colors**", "Use `border-border`", "```text",
  "### Global Accessibility Baseline", "`prefers-reduced-motion: reduce`", "`:focus-visible`",
  "### Mobile Install Baseline", "Add to Home Screen", "business pages must not listen for `beforeinstallprompt`",
];

export const DESIGN_CSS_MARKERS = [
  "border-border", "bg-status-error-muted text-status-error", "bg-status-success-muted text-status-success",
  "bg-status-warning-muted text-status-warning", "bg-status-info-muted text-status-info",
  "@media (prefers-reduced-motion: reduce)", "animation-duration: 0.01ms !important", "transition-duration: 0.01ms !important",
  "scroll-behavior: auto !important", ":focus-visible", "[tabindex]:focus-visible", '[tabindex="-1"]:focus',
  ".btn-primary:focus-visible", "outline: 2px solid var(--accent)", "box-shadow: var(--shadow-focus)",
  ".pwa-safe-area-shell", "min-height: 100dvh", "env(safe-area-inset-top)", "env(safe-area-inset-bottom)",
];

export const CONFIDENCE_BADGE_CASES = [
  ["TRUSTED", "badge-success"],
  ["HIGH", "badge-info"],
  ["MEDIUM", "badge-warning"],
  ["LOW", "badge-muted"],
] as const;

export const LOGIN_USER = (id: string, email: string, access_token: string) => ({
  id, email, name: null, created_at: "2026-01-01T00:00:00Z", access_token,
});

export const API_FN_CASES = [
  [OPS.AI_GET, undefined, "GET", /\/api\/users\/me\/settings$/, { enable_ai_reconciliation: true }],
  [OPS.AI_PATCH, { body: { enable_ai_classification: true } }, "PATCH", /\/api\/users\/me\/settings$/, { enable_ai_classification: true }],
  [OPS.BASE_CURR, undefined, "GET", /\/api\/users\/me\/settings\/base-currency$/, { base_currency: "SGD" }],
  [OPS.PUT_BASE_CURR, { body: { base_currency: "USD" } }, "PUT", /\/api\/users\/me\/settings\/base-currency$/, { base_currency: "USD" }],
] as const;

export const ADVISOR_HREF_CASES = [
  ["https://evil.example/review", "/"], ["//evil.example/reports", "/"], ["/ping-pong", "/"],
  ["/portfolio/AAPL", "/"], ["/portfolio?panel=prices&source=advisor", "/portfolio?panel=prices"],
  ["/portfolio?panel=evil", "/portfolio"], ["/reconciliation?tab=review-queue", "/reconciliation?tab=review-queue"],
  ["/reports/", "/reports"], ["/events#top", "/upload"],
] as const;

export const NAV_LABEL_CASES = [
  ["/reports", "Reports"], ["/reports/x", "Reports"], ["", "Page"], ["/chat", "Chat"],
  ["/audit", "Audit"], ["/more", "More"], ["/settings", "Settings"], ["/portfolio/A", "Portfolio"],
  ["/", "Home"], ["/upload", "Upload"], ["/custom-report_page", "Custom Report Page"],
] as const;

export const NAV_ACTIVE_CASES = [
  ["/", "/", true], ["/reports", "/", false], ["/reports", "/reports", true],
  ["/portfolio/p", "/portfolio", true], ["/reportsx", "/reports", false], ["/journal", "/reports", false],
] as const;

export const HUMANIZE_PKG_PROPS = {
  contract: HUMANIZE_PKG_CONTRACT,
  reportDate: "2026-05-20",
  startDate: "2025-05-20",
  selectedFrameworkLabel: "US-like",
};

export function runOtelWithNoWindow(fn: () => void) {
  const w = globalThis.window;
  // @ts-expect-error SSR simulation
  delete globalThis.window;
  try { fn(); } finally { globalThis.window = w; }
}

export function makeOtelEventTarget() {
  const ls: Record<string, (e: unknown) => void> = {};
  const target = { addEventListener: (k: string, h: (e: unknown) => void) => { ls[k] = h; } } as unknown as Window;
  return { ls, target };
}

export function runOtelVitalsCheck(
  captureWebVitals: (p: ReturnType<typeof fakeOtelProvider>["provider"], cfg: typeof OTEL_CFG, fns: { onCLS?: (cb: (m: { name: string; value: number }) => void) => void }) => void,
) {
  const v = fakeOtelProvider();
  let cb: ((m: { name: string; value: number }) => void) | undefined;
  captureWebVitals(v.provider, OTEL_CFG, { onCLS: (f) => { cb = f; } });
  cb?.({ name: "CLS", value: 0.1 });
  expect(v.setAttribute).toHaveBeenCalledWith("webvital.name", "CLS");
  expect(v.end).toHaveBeenCalledTimes(1);
  expect(() => captureWebVitals(v.provider, OTEL_CFG, {})).not.toThrow();
}

export async function checkChatBrief() {
  const b = await screen.findByLabelText("Advisor Brief");
  expect(within(b).getByText("Report package is blocked by one review-required item.")).toBeInTheDocument();
  expect(within(b).getByRole("link", { name: "Open next action" })).toHaveAttribute("href", "/reports?tab=package");
}

export function checkChatTable(container: HTMLElement) {
  hasTxts("The above analysis is for reference only.");
  expect(container.querySelector("table")).toBeInTheDocument();
  expect(container.querySelector("strong")).toBeInTheDocument();
  expect((screen.getByPlaceholderText(/Ask about spending trends/i) as HTMLTextAreaElement).value).toBe("Analyze this account");
}

export const cardInput = (title: string, label: string) =>
  within(screen.getByText(title).closest(".card") as HTMLElement).getByLabelText(label);

export async function checkLlmLoaded() {
  hasTxts("Loading LLM settings...");
  await screen.findByText("LLM Models");
  hasTxts("Extraction · OCR", "Advisor · Chat", "Statement · Summary");
  expect(screen.getAllByLabelText("Model")).toHaveLength(5);
  expect(screen.getByDisplayValue("openrouter/auto")).toBeInTheDocument();
}

export const LLM_PUT_BODY = {
  body: {
    bindings: expect.arrayContaining([
      expect.objectContaining({ scene: "advisor.chat", reasoning: "high" }),
      expect.objectContaining({ scene: "extraction.ocr" }),
    ]),
  },
};

export async function checkCockpitDeepLinks() {
  for (const t of ["balance sheet", "income statement", "cash flow"]) {
    chkLnk(`Open the ${t} report`, `/reports?period=1Q&end=2026-03-31&tab=${t.replace(" ", "-")}`);
  }
  for (const [id, lbl, val] of COCKPIT_METRICS) {
    await waitFor(() => expect(metricEl(id, lbl)).toHaveTextContent(val));
  }
  hasTxts("Opening balances not recorded");
}

export function checkSidebarAuthLinks(container: HTMLElement) {
  for (const [n, h] of SIDEBAR_NAV_LINKS) chkLnk(n, h);
  expect(container.querySelector("aside")).toHaveClass("w-64");
  for (const l of SIDEBAR_HIDDEN_LINKS) expect(screen.queryByRole("link", { name: l })).toBeNull();
}

export function checkTabsKeyboard(push: ReturnType<typeof vi.fn>, setActiveTab: ReturnType<typeof vi.fn>) {
  const nav = screen.getByRole("navigation", { name: "Open workspace tabs" });
  expect(within(nav).getByRole("list")).toBeInTheDocument();
  expect(screen.queryByRole("tablist")).toBeNull();
  expect(within(nav).getByRole("link", { name: /Dashboard/ })).toHaveAttribute("aria-current", "page");
  for (const key of ["ArrowRight", "ArrowLeft"]) {
    setActiveTab.mockClear(); push.mockClear();
    fireEvent.keyDown(nav, { key });
    expect(setActiveTab).toHaveBeenCalledWith("tab-2");
    expect(push).toHaveBeenCalledWith("/settings?tab=accounts");
  }
}

export function mockAccountsNudgeRoutes(api: ApiMockFn) {
  let calls = 0;
  mockAccountsStd(api, {
    get_opening_balance_readiness_status_accounts_opening_balance_readiness_get: { needs_opening_balance: true, earliest_activity_date: "2026-01-15" },
    [OPS.ACC_LIST]: () => {
      const items = [makeAccount({ id: "a1", name: "Cash", code: "1000", description: "Operating cash" })];
      if (++calls > 1) items.push(makeAccount({ id: "a2", name: "Savings", balance: "5000" }));
      return listOfAccounts(items);
    },
  });
}

export function checkPwaManifestAndShell(manifestRaw: string, shellSrc: string) {
  const m = JSON.parse(manifestRaw);
  expect(m).toMatchObject({ id: "/", start_url: "/", scope: "/", display: "standalone" });
  expect(m.icons).toEqual(expect.arrayContaining([
    expect.objectContaining({ src: "/icon-192.png", sizes: "192x192", type: "image/png" }),
    expect.objectContaining({ src: "/icon-512.png", sizes: "512x512", type: "image/png" }),
    expect.objectContaining({ src: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }),
  ]));
  expect(shellSrc).toContain("pwa-safe-area-shell");
  expect(shellSrc).toMatch(/<InstallAppPrompt\b[^>]*\/>/);
}

export const PWA_IOS_NAV = {
  maxTouchPoints: 1,
  platform: "iPhone",
  userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)",
};

export function checkRouteMapIntegrity(routes: { path: string; state: string; into?: string }[], pages: string[], targetCount: number) {
  const byPath = new Map(routes.map((r) => [r.path, r]));
  expect(pages.length).toBeGreaterThan(0);
  const paths = routes.map((r) => r.path);
  expect(new Set(paths).size).toBe(paths.length);
  expect(routes.filter((r) => r.state !== "redirect").map((r) => r.path).sort()).toEqual(pages);
  expect(routes.filter((r) => r.state === "target")).toHaveLength(targetCount);
  for (const r of routes) {
    expect(["target", "shell", "redirect"]).toContain(r.state);
    expect(Object.keys(r).filter((k) => !["path", "state", "into"].includes(k))).toEqual([]);
    if (r.state === "redirect") {
      expect(pages).not.toContain(r.path);
      const dest = byPath.get((r.into ?? "").split("?")[0]);
      expect(dest).toBeDefined(); expect(dest?.state).not.toBe("redirect");
    }
  }
  return byPath;
}

export async function settleHomeBudget(api: ApiMockFn) {
  await waitFor(() => expect(screen.getByText("Net worth").nextElementSibling).toHaveTextContent("$4,000"));
  await waitFor(() => expect(screen.getByText("Net change").nextElementSibling).toHaveTextContent("+$2,300"));
  for (const op of [OPS.REC_PEND, OPS.REC_UNM]) await waitFor(() => expect(api.mock.calls.map(([id]) => id)).toContain(op));
}

export const OB_INVALIDATION_KEYS = [["accounts"], ["report", "balance-sheet"], ["dashboard"]] as const;

export const PORTFOLIO_DONUT_MOCK = [
  { category: "Technology", value: "4810.00", percentage: "48.1", count: 1 },
  { category: "Unknown", value: "5190.00", percentage: "51.9", count: 2 },
];

export async function checkPortfolioTrustPanel() {
  const panel = await screen.findByRole("region", { name: "Net Worth Allocation" });
  expect(await within(panel).findByRole("link", { name: "HDB Valuation Report 2025-Q1 Long Identifier Without Spaces" })).toHaveClass("block", "truncate");
  for (const t of ["Gross share of net worth", "Liability offset of net worth"]) expect(within(panel).getByText(t)).toBeInTheDocument();
  expect(within(panel).getByTestId("allocation-bar-asset")).toHaveStyle({ width: "93.7%" });
  expect(within(panel).getByTestId("allocation-bar-liability")).toHaveStyle({ width: "100.0%" });
}

export const AI_S1 = { enable_ai_reconciliation: false, enable_ai_classification: true, auto_accept_ai_suggestions: true, auto_accept_ai_suggestions_active: true };
export const AI_S2 = { enable_ai_reconciliation: false, enable_ai_classification: false, auto_accept_ai_suggestions: true, auto_accept_ai_suggestions_active: false };

export const journalSampleRes = () => ({
  items: [makeJournalEntry("d1", "draft", "Draft Entry", 120, "bank_statement"), makeJournalEntry("p1", "posted", "Posted Entry", 300)],
});

export function fillJournalLines(amt: string) {
  const s = screen.getAllByRole("combobox"), a = screen.getAllByPlaceholderText("0.00");
  fireEvent.change(s[0], { target: { value: "a1" } }); fireEvent.change(s[2], { target: { value: "a2" } });
  fireEvent.change(a[0], { target: { value: amt } }); fireEvent.change(a[1], { target: { value: amt } });
}

export const ACTION_BASE_ROUTES = {
  [OPS.REC_STATS]: makeStats(),
  [OPS.STMT_LIST]: { items: [], total: 0 },
  [OPS.REC_PEND]: { items: [], total: 0 },
  [OPS.REC_UNM]: { items: [], total: 0 },
};

export const ACTION_QUEUE_ITEMS = [
  { id: "reconciliation:unmatched", kind: "unmatched_transactions", title: "ACME and 3 more", detail: "4 unmatched", reason: "", confidence: 0, href: "/reconciliation?tab=unmatched" },
  { id: "statement:s-oct", kind: "statement_review", title: "oct.csv", detail: "Parsed — ready to review", reason: "", confidence: 95, href: "/statements/s-oct" },
];

export const WS_STORED = JSON.stringify({ tabs: [{ id: "s1", label: "Stored Dashboard", href: "/dashboard" }, { id: "s2", label: "Stored Reports", href: "/reports" }], activeTabId: "s2" });
export const WS_REMOTE = JSON.stringify({ tabs: [{ id: "r1", label: "Remote", href: "/remote" }], activeTabId: "r1" });

export const API_422_TEXT = JSON.stringify({ detail: [{ msg: "Field required" }], error_id: "validation_error", request_id: "req-v1" });

export const stmtShort = (id: string, status: string) =>
  makeStatement({ id, original_filename: `${id}.pdf`, status, currency: undefined, period_start: undefined, period_end: undefined, opening_balance: undefined, closing_balance: undefined, confidence_score: undefined, balance_validated: undefined });

export const mockStmtPages = (api: ApiMockFn, pages: Array<{ items: unknown[]; total: number }>) => {
  let reads = 0;
  mockApiMap(api, { [OPS.STMT_LIST]: () => pages[Math.min(reads++, pages.length - 1)], [OPS.REC_STATS]: makeStats(), [OPS.REC_PEND]: { items: [], total: 0 } }, null);
};

export const DRAFT_2765 = { accountId: "acc-1", currency: "SGD", periodStart: "2026-01-01", periodEnd: "2026-01-31", openingBalance: "1000.00", closingBalance: "1200.00", rationale: "" };

export const DESIGN_EXTEND_MATCHER = {
  colors: {
    surface: { DEFAULT: "var(--background)", card: "var(--background-card)", muted: "var(--background-muted)", overlay: "var(--overlay)" },
    content: { DEFAULT: "var(--foreground)", muted: "var(--foreground-muted)", inverse: "var(--foreground-inverse)" },
    border: { DEFAULT: "var(--border)", hover: "var(--border-hover)" },
    accent: { DEFAULT: "var(--accent)", hover: "var(--accent-hover)", muted: "var(--accent-muted)" },
    status: { success: "var(--success)", warning: "var(--warning)", error: "var(--error)", info: "var(--info)" },
    chart: { 1: "var(--chart-1)", 5: "var(--chart-5)", "trend-start": "var(--chart-trend-start)" },
  },
  borderRadius: { control: "var(--radius-md)", panel: "var(--radius-lg)" },
  fontSize: { caption: ["var(--font-size-caption)", { lineHeight: "var(--line-height-caption)" }], body: ["var(--font-size-body)", { lineHeight: "var(--line-height-body)" }], title: ["var(--font-size-title)", { lineHeight: "var(--line-height-title)" }] },
  spacing: { page: "var(--space-page)", panel: "var(--space-panel)", control: "var(--space-control)" },
  boxShadow: { card: "var(--shadow-card)", floating: "var(--shadow-floating)" },
  zIndex: { overlay: "var(--z-overlay)", modal: "var(--z-modal)" },
  transitionDuration: { fast: "var(--motion-duration-fast)", standard: "var(--motion-duration-standard)" },
  transitionTimingFunction: { standard: "var(--motion-ease-standard)" },
};

export const OVERFLOW_HOLDING = makeHolding({ asset_identifier: "VWRA", quantity: "42.5", cost_basis: "5000.00", market_value: "5450.00" });
export const OVERFLOW_UNMATCHED = { items: [{ id: "txn-1", statement_id: "s1", txn_date: "2026-02-01", description: "LONG_MERCHANT", amount: "-980.50", currency: "SGD", direction: "OUT", status: "unmatched" }], total: 1 };

export const COV_2763 = { start: "2025-03-01", limitingAccounts: ["DBS USD", "Wise EUR"], latestStatementEnd: "2025-03-31" };
export const COV_2763_ROUTES = {
  [OPS.COV]: (r: { query?: Record<string, unknown> }) => ({ as_of_date: r.query?.as_of_date, coverage_start: "2025-03-01", limiting_accounts: ["DBS USD", "Wise EUR"], latest_statement_end: "2025-03-31" }),
  [OPS.CURR]: ["SGD"],
  [OPS.BASE_CURR]: { base_currency: "SGD" },
};
export const OB_WARNINGS_2763 = [
  { type: "missing_opening_balance", account_name: "DBS USD", message: "No opening balance recorded before 2025-03-01." },
  { type: "missing_opening_balance", account_name: "Wise EUR", earliest_activity_date: "2025-03-10" },
];

export const ATTN_OK = makeStats({ total_transactions: 10, matched_transactions: 10, unmatched_transactions: 0, pending_review: 0, auto_accepted: 10, match_rate: 100 });
export const ATTN_BAD_STMT = makeStatement({ id: "bad", original_filename: "bad.pdf", confidence_score: 88, balance_validated: false });
export const ATTN_LATE_STMT = makeStatement({ id: "late", original_filename: "late.pdf", confidence_score: 55 });

export const NAV_EXCLUDED_TABS = ["/journal", "/reconciliation", "/settings?tab=accounts", "/statements", "/settings"];
export const NAV_UUID = "3f2b8c1e-9d4a-4e57-8a60-1c2d3e4f5a6b";

export const confirmDlgMock = (confirmLabel = "Confirm Delete", cancelLabel = "Cancel Delete", reason?: string, fixedLabel = false) => ({
  default: ({ isOpen, onConfirm, onCancel, title, confirmLabel: cl }: { isOpen: boolean; onConfirm: (r?: string) => void; onCancel: () => void; title?: string; confirmLabel?: string }) =>
    isOpen
      ? createElement("div", { "data-testid": "confirm-dialog" },
          title ? createElement("span", null, title) : null,
          createElement("button", { onClick: () => onConfirm(reason) }, fixedLabel ? confirmLabel : (cl ?? confirmLabel)),
          createElement("button", { onClick: onCancel }, cancelLabel))
      : null,
});

export const openingModalMock = {
  default: ({ isOpen, onSuccess, onClose }: { isOpen: boolean; onSuccess?: () => void; onClose?: () => void }) =>
    isOpen
      ? createElement("div", null, "Opening Balance Modal",
          onSuccess ? createElement("button", { onClick: onSuccess }, "Mock Record Balances") : null,
          onClose ? createElement("button", { onClick: onClose }, "Mock Close Opening") : null)
      : null,
};

export const accountFormMock = {
  default: ({ isOpen, editAccount, onSuccess, onClose }: { isOpen: boolean; editAccount: Account | null; onSuccess?: () => void; onClose?: () => void }) =>
    isOpen
      ? createElement("div", null, editAccount ? `Edit:${editAccount.name}` : "Create Account Modal",
          onSuccess ? createElement("button", { onClick: onSuccess }, "Mock Save") : null,
          onClose ? createElement("button", { onClick: onClose }, "Mock Close") : null)
      : null,
};

export const uploaderMock = (label = "Done") => ({
  default: ({ onUploadComplete }: { onUploadComplete?: () => void }) =>
    createElement("button", { type: "button", onClick: () => onUploadComplete?.() }, label),
});

export function runOtelInitChecks(
  O: typeof import("@/lib/otel"),
  M: { url: { c: string | undefined }; res: { c: Record<string, unknown> | undefined }; reg: ReturnType<typeof vi.fn> },
) {
  expect(O.sanitizeAttributes(OTEL_RAW_ATTRS)).toEqual(OTEL_CLEAN_ATTRS);
  expect([O.initOtel({}), O.initOtel(OTEL_ENV), O.initOtel(OTEL_ENV)]).toEqual([false, true, false]);
  expect(M.url.c).toBe(OTEL_CFG.endpoint);
  expect(M.reg).toHaveBeenCalledTimes(1);
  expect(M.res.c).toMatchObject({ s: "finance-report-frontend", v: "abc123", "deployment.environment": "staging" });
  O.resetOtelForTests();
  runOtelWithNoWindow(() => expect(O.initOtel(OTEL_ENV)).toBe(false));
  M.reg.mockImplementationOnce(() => { throw new Error("boom"); });
  expect(O.initOtel(OTEL_ENV)).toBe(false);
}

export function runOtelSpanAndErrorChecks(O: typeof import("@/lib/otel")) {
  const s = { setAttribute: vi.fn() };
  O.scrubSpanUrlAttributes(s, "https://x.com/p?s=1#f");
  for (const k of OTEL_SPAN_KEYS) expect(s.setAttribute).toHaveBeenCalledWith(k, "https://x.com/p");
  expect(s.setAttribute).toHaveBeenCalledWith("url.query", "");
  s.setAttribute.mockClear();
  O.scrubSpanUrlAttributes(s, undefined);
  expect(s.setAttribute).toHaveBeenCalledTimes(1);
  runOtelVitalsCheck(O.captureWebVitals);
  const f = fakeOtelProvider(), { ls, target } = makeOtelEventTarget();
  O.installErrorHooks(f.provider, OTEL_CFG, target);
  for (const [ev, p, n] of OTEL_ERR_CASES) {
    ls[ev](p);
    if (n) expect(f.recordException).toHaveBeenCalledWith({ name: n, message: "[redacted]" });
  }
  expect(f.setAttribute).toHaveBeenCalledWith("exception.source", "onerror");
  withDefinedProps([[window, "location", { get() { throw new Error("x"); } }]], () => {
    O.installErrorHooks(f.provider, OTEL_CFG, target);
    expect(() => ls.error({ error: new Error("x") })).not.toThrow();
  });
}

export async function runChatSessionsFlow(api: ApiMockFn, stream: ReturnType<typeof vi.fn>) {
  fireEvent.click(await screen.findByRole("button", { name: "Sessions" }));
  const dlg = await dlgEl("AI sessions");
  clkBtn("Close panel");
  await waitFor(() => expect(dlg).not.toBeInTheDocument());
  expect(localStorage.getItem("ai_chat_session_id")).toBe("sess-1");
  clkBtn("Sessions");
  await dlgEl("AI sessions");
  clkTxt("Cash flow review");
  await waitOp(api, OPS.CHAT_HIST, expect.objectContaining({ query: expect.objectContaining({ session_id: "sess-1" }) }));

  const ta = screen.getByPlaceholderText(/Ask about spending trends/i);
  expect(btn("Send")).toBeDisabled();
  fireEvent.change(ta, { target: { value: "Hello" } });
  fireEvent.keyDown(ta, { key: "Enter", shiftKey: false });
  await waitFor(() => expect(stream).toHaveBeenCalledTimes(1));
  fireEvent.change(ta, { target: { value: "Hello 2" } });
  clkBtn("Send");
  await waitFor(() => expect(stream).toHaveBeenCalledTimes(2));
}

export async function runCockpitDrillFlow(api: ApiMockFn) {
  const sw = await screen.findByRole("tablist", { name: "Statement switcher" });
  const rows = await screen.findAllByRole("button", { name: /View source transactions for/ });
  expect(rows.map((r) => r.getAttribute("aria-label"))).toEqual(COCKPIT_EXPECTED_ROWS);
  for (const [tab, b, account_id, start_date] of COCKPIT_DRILL_CASES) {
    if (tab) fireEvent.click(within(sw).getByRole("tab", { name: tab }));
    fireEvent.click(b ? await screen.findByRole("button", { name: b }) : rows[0]);
    await waitOp(api, OPS.LIN, { query: { account_id, as_of_date: "2026-03-31", currency: "SGD", start_date } });
    if (tab === "Cash") expect(screen.queryByRole("button", { name: "View source transactions for Broker transfer" })).toBeNull();
    else clkBtn("Close panel");
  }
}

export async function runLlmEditAndSave(api: ApiMockFn, showToast: ReturnType<typeof vi.fn>) {
  await screen.findByText("LLM Models");
  const save = btn(/Save changes/i);
  expect(save).toBeDisabled();
  fireEvent.change(cardInput("Advisor · Chat", "Reasoning depth"), { target: { value: "high" } });
  clkBtn(/Reset/i);
  expect(cardInput("Advisor · Chat", "Reasoning depth")).toHaveValue("low");
  expect(save).toBeDisabled();
  fireEvent.change(cardInput("Extraction · OCR", "Provider"), { target: { value: "prov-1" } });
  fireEvent.change(cardInput("Extraction · OCR", "Model"), { target: { value: "some-model" } });
  fireEvent.change(cardInput("Advisor · Chat", "Reasoning depth"), { target: { value: "high" } });
  fireEvent.click(save);
  await waitOp(api, OPS.LLM_SCENES_PUT, LLM_PUT_BODY);
  await waitFor(() => expect(showToast).toHaveBeenCalledWith("LLM bindings saved", "success"));
}

export async function runLlmDeleteSuccess(api: ApiMockFn, showToast: ReturnType<typeof vi.fn>) {
  const del = await screen.findByRole("button", { name: /Delete provider OpenRouter/i });
  fireEvent.click(del);
  await dlgEl();
  clkBtn(/Cancel/i);
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(api).not.toHaveBeenCalledWith(OPS.LLM_PROV_DEL, expect.anything());
  fireEvent.click(del);
  fireEvent.click(await screen.findByRole("button", { name: "Delete provider" }));
  await waitFor(() => expect(showToast).toHaveBeenCalledWith("Provider deleted", "success"));
  await screen.findByText(/No providers configured yet/i);
}

export async function runSidebarLogoutSuccess(
  api: ApiMockFn,
  clearUser: ReturnType<typeof vi.fn>,
  push: ReturnType<typeof vi.fn>,
  done: () => void,
  container: HTMLElement,
) {
  await screen.findByRole("link", { name: /^Home$/i });
  checkSidebarAuthLinks(container);
  clkBtn("Logout");
  expect(api).toHaveBeenCalledWith(OPS.LOGOUT);
  expect(clearUser).not.toHaveBeenCalled();
  expect(btn("Logout")).toBeDisabled();
  done();
  await waitFor(() => expect(clearUser).toHaveBeenCalledTimes(1));
  expect(push).toHaveBeenCalledWith("/login");
}

export async function runAccountsDeleteFlow(
  api: ApiMockFn,
  showToast: ReturnType<typeof vi.fn>,
  probe: { expectNothingInvalidated: () => void; expectDeclaredInvalidated: () => void },
) {
  await screen.findByText("Cash");
  probe.expectNothingInvalidated();
  clkBtn("Delete Account");
  clkTxt("Cancel Delete");
  await waitFor(() => expect(screen.queryByTestId("confirm-dialog")).toBeNull());
  expect(api).not.toHaveBeenCalledWith(OPS.ACC_DEL, expect.anything());
  clkBtn("Delete Account");
  clkTxt("Confirm Delete");
  await waitOp(api, OPS.ACC_DEL, { path: { account_id: "a1" } });
  expect(showToast).toHaveBeenCalledWith("Account deleted successfully", "success");
  await waitFor(() => probe.expectDeclaredInvalidated());
}

export async function runAccountsNudgeFlow(showToast: ReturnType<typeof vi.fn>) {
  const nudge = await screen.findByText(/Your balance sheet may be incomplete/);
  hasTxts(/since 2026-01-15/);
  fireEvent.click(within(nudge.closest('[role="status"]') as HTMLElement).getByRole("button", { name: /Set opening balances/i }));
  hasTxts("Opening Balance Modal");
  clkTxt("Mock Record Balances");
  expect(showToast).toHaveBeenCalledWith("Opening balances recorded", "success");
  clkTxt("Mock Close Opening");
  await waitFor(() => noTxt("Opening Balance Modal"));
  clkTxt("Cash");
  await dlgEl("Account Details");
  clkBtn("Close panel");
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Account Details" })).toBeNull());
  fireEvent.click(screen.getAllByRole("button", { name: "Edit Account" })[0]);
  hasTxts("Edit:Cash");
  clkTxt("Mock Close");
  await waitFor(() => noTxt("Edit:Cash"));
  clkTxt("Add Account");
  hasTxts("Create Account Modal");
  clkTxt("Mock Save");
  await screen.findByText("Savings");
}

export async function runRouteRedirectsCheck(
  red: Array<{ source: string; destination: string; permanent?: boolean }>,
  routes: Array<{ path: string; state: string; into?: string }>,
  pages: string[],
  byPath: Map<string, { path: string; state: string; into?: string }>,
  getPathMatch: typeof import("next/dist/shared/lib/router/utils/path-match").getPathMatch,
  prepareDestination: typeof import("next/dist/shared/lib/router/utils/prepare-destination").prepareDestination,
) {
  const toNext = (p: string) => p.replace(/\[([^\]]+)\]/g, ":$1");
  expect(red.map((r) => `${r.source} -> ${r.destination} ${r.permanent ? "permanent" : "temporary"}`).sort())
    .toEqual(routes.filter((r) => r.state === "redirect").map((r) => `${toNext(r.path)} -> ${toNext(r.into ?? "")} permanent`).sort());
  const byS = new Map(red.map((r) => [r.source, r.destination]));
  for (const [f, t] of Object.entries(ROUTE_RETIRED_UPLOAD)) {
    expect(byPath.get(f)).toMatchObject({ state: "redirect", into: t });
    expect(byS.get(toNext(f))).toBe(toNext(t));
  }
  const dest = (s: string) => red.find((r) => r.source === s)?.destination;
  for (const [o, s, d] of ROUTE_AUDIT_REDIRECTS) { expect(dest(s)).toBe(d); expect(byPath.get(o)?.state).toBe("redirect"); expect(pages).not.toContain(o); }
  for (const t of ["balance-sheet", "income-statement", "cash-flow", "package"]) { const o = `/reports/${t}`; expect(dest(o)).toBe(`/reports?tab=${t}`); expect(byPath.get(o)?.state).toBe("redirect"); expect(pages).not.toContain(o); }
  expect(red.filter((r) => r.source.startsWith("/reports/"))).toHaveLength(4);
  for (const [f, pathname, query] of ROUTE_QUERY_REDIRECTS) {
    const u = new URL(f, "http://app.test"); let got: unknown = null;
    for (const r of red) {
      const p = getPathMatch(r.source, { strict: true, removeUnnamedParams: true })(u.pathname);
      if (p) { const { parsedDestination: d } = prepareDestination({ appendParamsToQuery: false, destination: r.destination, params: p, query: Object.fromEntries(u.searchParams) }); got = { pathname: d.pathname, query: { ...d.query } }; break; }
    }
    expect(got).toEqual({ pathname, query });
  }
  for (const o of ROUTE_LEGACY_DELETED) { expect(byPath.get(o)?.state).toBe("redirect"); expect(pages).not.toContain(o); }
}

export async function runHomeBudgetMutations(api: ApiMockFn) {
  api.mockClear();
  fireEvent.click(screen.getByLabelText("Include restricted holdings"));
  await waitFor(() => expect(screen.getByText("Liquid net worth").nextElementSibling).toHaveTextContent("$1,500"));
  expect(homeCallKeys(api).map((k) => k.split(" ")[0])).toEqual([OPS.BS, OPS.BS]);
  api.mockClear();
  clkBtn("Period 1M");
  await waitFor(() => expect(homeCallKeys(api)).toHaveLength(3));
  expect(homeCallKeys(api).map((k) => k.split(" ")[0]).sort()).toEqual([OPS.BS, OPS.CF, OPS.IS]);
}

export function runLoginControlChecks() {
  const tog = screen.getByTestId("auth-mode-toggle-register"), cta = screen.getByTestId("login-register-cta");
  expect(tog).not.toBe(cta);
  expect(tog).toHaveAccessibleName("Register (switch to register mode)");
  expect(cta).toHaveAccessibleName("Register a new account");
  expect(screen.queryAllByRole("button", { name: /^Register$/ })).toHaveLength(0);
  const pw = screen.getByLabelText("Password") as HTMLInputElement;
  expect(pw.type).toBe("password"); clkBtn("Show password"); expect(pw.type).toBe("text"); clkBtn("Hide password"); expect(pw.type).toBe("password");
  fireEvent.click(screen.getByText("Don't have an account?").closest("p")!.querySelector("button")!);
  fireEvent.click(screen.getByText("Already have an account?").closest("p")!.querySelector("button")!);
  hasTxts("Don't have an account?");
}

export function checkOverflowBsDom() {
  expect(btn("Margin Cash Account With Very Long Label")).toHaveClass("line-clamp-2", "break-words");
  for (const id of ["assets", "liabilities", "equity"]) expect(document.getElementById(id)!).toHaveClass("min-w-0", "overflow-hidden");
  expect(within(document.getElementById("equity")!).getByText("Total:").nextElementSibling).toHaveClass("whitespace-nowrap", "shrink-0");
}

export function checkOverflowHoldingsDom(c: HTMLElement) {
  expect(c.querySelector(".card")).toHaveClass("overflow-hidden", "min-w-0");
  expect(screen.getByRole("columnheader", { name: "Cost Basis" })).toHaveClass("hidden", "md:table-cell");
  expect(screen.getByRole("columnheader", { name: "Status" })).toHaveClass("hidden", "lg:table-cell");
  expect(screen.getByText("SGD 5,450.00")).toHaveClass("whitespace-nowrap", "tabular-nums");
}

export function checkDesignTokenMatches(extend: Record<string, unknown>, ssot: string, globals: string) {
  expect(extend).toMatchObject(DESIGN_EXTEND_MATCHER);
  for (const m of DESIGN_SSOT_MARKERS) expect(ssot).toContain(m);
  for (const m of DESIGN_CSS_MARKERS) expect(globals).toContain(m);
  expect(globals).not.toContain("border-[var(--border)]");
  expect(globals).not.toContain('[tabindex]:not([tabindex="-1"])');
  expect(globals).not.toMatch(/alert bg-\[var\(--(error|success|warning|info)-muted\)\] text-\[var\(--(error|success|warning|info)\)\]/);
}

export function checkAdvisorBriefAllRoutes(safeAdvisorHref: (u: string) => string, routes: Array<{ path: string; state: string; into?: string }>) {
  for (const [i, o] of ADVISOR_HREF_CASES) expect(safeAdvisorHref(i)).toBe(o);
  const red = routes.filter((r) => r.state === "redirect" && !r.path.includes("[") && !r.into?.includes(":"));
  const tgt = routes.filter((r) => r.state === "target" && !r.path.includes("["));
  expect(red.length > 20 && tgt.length > 5).toBe(true);
  for (const r of red) expect(safeAdvisorHref(r.path), r.path).toBe(r.into);
  for (const r of tgt) expect(safeAdvisorHref(r.path), r.path).toBe(r.path);
}

export function checkNavigationRoutes(N: typeof import("@/components/navigation"), routes: Array<{ path: string; state: string }>) {
  const tabs = N.bottomTabItems.map((i) => i.href), audit = N.auditHubItems.map((i) => i.href);
  expect(N.bottomTabItems.map((i) => [i.label, i.href])).toEqual([["Home", "/"], ["Chat", "/chat"], ["Audit", "/audit"], ["More", "/more"]]);
  expect(N.ADD_ACTION.label).toBe("Add");
  for (const h of [...NAV_EXCLUDED_TABS, ...audit]) expect(tabs).not.toContain(h);
  expect(new Set(N.bottomTabItems.map((i) => i.icon)).size).toBe(4);
  expect(audit).toEqual(expect.arrayContaining(["/reconciliation", "/journal", "/upload"]));
  expect(N.moreItems.map((i) => i.href)).toEqual(["/portfolio", "/reports", "/settings"]);
  expect(N.advancedItems.map((i) => i.href)).toContain("/settings?tab=accounts");
  expect([...N.bottomTabItems, ...N.auditHubItems, ...N.moreItems, ...N.advancedItems].filter((i) => i.label === "Portfolio").map((i) => i.href)).toEqual(["/portfolio"]);
  for (const [p, l] of NAV_LABEL_CASES) expect(N.getRouteConfig(p).label).toBe(l);
  expect(N.getRouteConfig("/unknown").Icon).toBe(N.DEFAULT_ROUTE_ICON);
  const redir = routes.filter((r) => r.state === "redirect").map((r) => r.path);
  expect(redir).toEqual(expect.arrayContaining(["/events", "/assets"]));
  for (const r of redir) expect(N.ROUTE_CONFIG[r], r).toBeUndefined();
  expect(N.getRouteConfig("/events")).toMatchObject({ Icon: N.DEFAULT_ROUTE_ICON, label: "Events" });
  const tgts = routes.filter((r) => r.state === "target" && r.path.includes("[")).map((r) => r.path);
  expect(tgts).toContain("/statements/[id]");
  for (const t of tgts) { const c = t.replace(/\[[^\]]+\]/g, NAV_UUID); expect(N.ROUTE_CONFIG[t], t).toBeDefined(); expect(N.getRouteConfig(c), c).toBe(N.ROUTE_CONFIG[t]); expect(N.getRouteConfig(c).label).not.toContain(NAV_UUID); }
  expect([N.getRouteConfig(`/statements/${NAV_UUID}`).label, N.getRouteConfig(`/statements/${NAV_UUID}/x`).label === "Statement"]).toEqual(["Statement", false]);
  for (const [p, h, ok] of NAV_ACTIVE_CASES) expect(N.isActive(p, h)).toBe(ok);
  for (const [k, r] of Object.entries(N.APP_ROUTES)) expect(N.ROUTE_CONFIG[r.split("?")[0]], k).toBeDefined();
  expect(N.APP_ROUTES).toMatchObject({ HOME: "/", UPLOAD: "/upload", AUDIT: "/audit", CHAT: "/chat", RECONCILIATION_REVIEW_QUEUE: "/reconciliation?tab=review-queue" });
}

export async function runPwaNativeChecks(
  usePwaInstall: () => { promptKind: string | null; isInstalled: boolean; promptInstall: () => Promise<void>; dismissPrompt: () => void },
  act: (fn: () => void | Promise<void>) => Promise<void> | void,
  renderHook: <T>(cb: () => T) => { result: { current: T } },
  dismissedKey: string,
  cooldownMs: number,
) {
  const { result } = renderHook(usePwaInstall), acc = makePwaPromptEvent("accepted");
  act(() => { window.dispatchEvent(acc); });
  expect(acc.preventDefault).toHaveBeenCalled();
  await waitFor(() => expect(result.current.promptKind).toBe("native"));
  await act(async () => { await result.current.promptInstall(); });
  expect(acc.prompt).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(result.current.isInstalled).toBe(true));

  const h2 = renderHook(usePwaInstall);
  act(() => h2.result.current.dismissPrompt());
  expect(localStorage.getItem(dismissedKey)).toMatch(/^\d+$/);
  act(() => { window.dispatchEvent(makePwaPromptEvent()); });
  expect(h2.result.current.promptKind).toBeNull();

  localStorage.clear();
  const h3 = renderHook(usePwaInstall);
  act(() => { window.dispatchEvent(makePwaPromptEvent("dismissed")); });
  await waitFor(() => expect(h3.result.current.promptKind).toBe("native"));
  await act(async () => { await h3.result.current.promptInstall(); });
  expect(h3.result.current.promptKind).toBeNull();

  vi.useFakeTimers(); vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
  setPwaNavigator(PWA_IOS_NAV);
  localStorage.setItem(dismissedKey, String(Date.now() - cooldownMs + 1000));
  try {
    const h4 = renderHook(usePwaInstall);
    expect(h4.result.current.promptKind).toBeNull();
    await act(async () => { vi.advanceTimersByTime(1001); await Promise.resolve(); });
    expect(h4.result.current.promptKind).toBe("ios");
  } finally { vi.useRealTimers(); }
}

export async function runOpeningBalDateChecks(
  api: ApiMockFn,
  rerender: (ui: ReactElement) => void,
  renderModal: (open: boolean) => ReactElement,
) {
  expect(screen.getByLabelText("Opening balance for Cash")).toBeInTheDocument();
  expect(screen.getByLabelText("Opening balance for Credit Card")).toBeInTheDocument();
  expect(screen.queryByLabelText("Opening balance for Salary")).toBeNull();
  expect(screen.queryByLabelText("Opening balance for Closed")).toBeNull();
  const date = screen.getByLabelText("As-of date *");
  chgLbl("First report period starts", "2026-03-01"); expect(date).toHaveValue("");
  clkBtn("Use 2026-02-28"); expect(date).toHaveValue("2026-02-28");
  chgLbl("As-of date *", "2026-02-27"); chgLbl("First report period starts", "2026-04-01"); expect(date).toHaveValue("2026-02-27");
  rerender(renderModal(false)); expect(screen.queryByRole("dialog")).toBeNull();
  rerender(renderModal(true)); expect(screen.getByLabelText("As-of date *")).toHaveValue("");
  chgLbl("As-of date *", "2025-01-01"); chgLbl("Memo", "Year-start positions"); chgLbl("Opening balance for Cash", "42.00");
  clkBtn("Record opening balances");
  await waitOp(api, OPS.OPEN_BAL, { body: { entry_date: "2025-01-01", balances: { a1: "42.00" }, memo: "Year-start positions" } });
}

export async function runJournalCrudActions(api: ApiMockFn) {
  await screen.findByText("Draft Entry");
  fireEvent.click(screen.getAllByRole("button", { name: "Post" })[0]);
  await waitOp(api, OPS.JE_POST, { path: { entry_id: "d1" } });
  fireEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);
  clkBtn("Delete Entry");
  await waitOp(api, OPS.JE_DEL, { path: { entry_id: "d1" } });
  fireEvent.click(screen.getAllByRole("button", { name: "Void" })[0]);
  clkBtn("Void Entry");
  await waitOp(api, OPS.JE_VOID, { path: { entry_id: "p1" }, body: { reason: "void reason" } });
}

export function stubWsStorage(store: Map<string, string>, uuid: ReturnType<typeof vi.fn>) {
  store.clear();
  uuid.mockReset().mockReturnValueOnce("tab-uuid-1").mockReturnValueOnce("tab-uuid-2").mockReturnValueOnce("tab-uuid-3");
  vi.stubGlobal("localStorage", { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => store.set(k, v), removeItem: (k: string) => store.delete(k) });
  vi.stubGlobal("crypto", { randomUUID: uuid });
  vi.spyOn(Math, "random").mockReturnValue(0.123456789);
}

export async function runWsCrudFlow(store: Map<string, string>) {
  store.clear();
  clkBtn("AddD"); clkBtn("AddR");
  await waitFor(() => expect(screen.getByTestId("act")).toHaveTextContent("tab-uuid-2"));
  expect(store.get("finance-workspace-tabs")).toContain("tab-uuid-1");
  clkBtn("AddD");
  await waitFor(() => expect(screen.getByTestId("act")).toHaveTextContent("tab-uuid-1"));
  expect((JSON.parse(screen.getByTestId("tabs").textContent ?? "[]") as unknown[]).length).toBe(2);
  clkBtn("Act1"); clkBtn("Rem2");
  await waitFor(() => expect(screen.getByTestId("act")).toHaveTextContent("tab-uuid-1"));
  clkBtn("Rem1");
  await waitFor(() => expect(screen.getByTestId("tabs")).toHaveTextContent("[]"));
}

export async function runApiClientStreamsCheck(
  fetchMock: ReturnType<typeof vi.fn>,
  streamFn: (op: never, req: never) => Promise<{ sessionId: string | null }>,
  uploadFn: (op: never, req: never) => Promise<unknown>,
  downloadFn: (op: never, req: never) => Promise<{ filename: string | null }>,
) {
  fetchMock.mockResolvedValueOnce({ ok: true, status: 200, headers: { get: (h: string) => (h.toLowerCase() === "x-session-id" ? "s1" : null) }, text: async () => "" });
  expect((await streamFn(OPS.CHAT_POST as never, { body: { message: "hi" } } as never)).sessionId).toBe("s1");
  const fd = new FormData();
  fetchMock.mockResolvedValueOnce({ ok: true, status: 204 });
  expect(await uploadFn(OPS.UPL as never, { body: fd } as never)).toBeUndefined();
  fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ id: "s1" }) });
  expect(await uploadFn(OPS.UPL as never, { body: fd } as never)).toEqual({ id: "s1" });
  const csv = new Blob(["data"], { type: "text/csv" });
  for (const [hdr, expected] of API_DOWNLOAD_CASES) {
    global.fetch = makeFetchMock(200, csv, hdr ? { "content-disposition": hdr } : {});
    expect((await downloadFn(OPS.EXP as never, { query: {} } as never)).filename).toBe(expected);
  }
  global.fetch = fetchMock as unknown as typeof fetch;
}

export async function runAttentionQueueChecks(api: ApiMockFn) {
  const rows = await screen.findAllByRole("link");
  expect(rows.map((r) => r.getAttribute("href"))).toEqual(["/reconciliation?tab=unmatched&from=attention", "/statements/bad?from=attention", "/reconciliation?tab=matches&from=attention"]);
  expect(within(rows[1]).getByText("bad.pdf")).toBeInTheDocument();
  expect(within(rows[1]).getByText(/balance didn't reconcile/i)).toBeInTheDocument();
  expect(within(rows[0]).getByText("0% confidence")).toBeInTheDocument();
  const r = within(rows[0]).getByText(/no matching ledger entry/i);
  expect(r).toHaveClass("text-muted");
  expect(r.className).not.toContain("text-muted/80");
  expect(api).toHaveBeenCalled();
}

export function checkBannerCard(heading: string, linkName: string, href: string, absentText?: string) {
  const b = screen.getByRole("region", { name: "Needs attention" });
  expect(within(b).getByRole("heading", { name: heading })).toBeInTheDocument();
  expect(within(b).getByRole("link", { name: linkName })).toHaveAttribute("href", href);
  if (absentText) expect(within(b).queryByText(absentText)).toBeNull();
}

export function checkCoveragePeriodNote(expectedText: string, btnDisabled = true) {
  expect(screen.getByTestId("report-period-range")).toHaveTextContent(expectedText);
  if (btnDisabled) expect(btn("Previous period")).toBeDisabled();
  else expect(btn("Previous period")).toBeEnabled();
}

export async function runChatErrorStates(
  renderChat: () => { unmount: () => void },
  stream: ReturnType<typeof vi.fn>,
) {
  stream.mockResolvedValueOnce({ response: { body: null } as never, sessionId: "s3" }).mockRejectedValueOnce(new Error("Network Fail"));
  const v1 = renderChat(); await waitFor(() => noTxt(/Loading chat history/i));
  const ta = screen.getByPlaceholderText(/Ask about spending trends/i);
  fireEvent.change(ta, { target: { value: "a" } }); clkBtn("Send"); await screen.findByText("No response stream available.");
  fireEvent.change(ta, { target: { value: "b" } }); clkBtn("Send");
  await waitFor(() => expect(screen.getAllByText("Network Fail").length).toBeGreaterThan(0));
  v1.unmount();
}

export async function runSidebarStates(
  renderSidebar: () => { unmount: () => void },
  setAuth: (ok: boolean, email: string | null) => void,
  setWs: (patch: Record<string, unknown>) => void,
  toggleSidebar: ReturnType<typeof vi.fn>,
  refresh: ReturnType<typeof vi.fn>,
) {
  setAuth(false, null);
  const u = renderSidebar(); await screen.findByRole("link", { name: "Login" });
  expect(screen.queryByRole("link", { name: /^Chat$/i })).toBeNull(); u.unmount();
  setAuth(true, "user@example.com"); setWs({ isCollapsed: true });
  const c = renderSidebar(); await screen.findByLabelText("Expand sidebar"); noTxt("user@example.com"); c.unmount();
  setWs({ isCollapsed: false }); renderSidebar();
  expect(await screen.findByRole("link", { name: /^Audit$/i })).toHaveAttribute("aria-current", "page");
  clkBtn("Collapse sidebar"); expect(toggleSidebar).toHaveBeenCalledTimes(1);
  clkBtn("Add"); fireEvent.click(within(screen.getByRole("dialog", { name: "Add" })).getByRole("button", { name: /Upload statement/i }));
  clkBtn("Done"); expect(refresh).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("dialog", { name: "Upload statement" })).toBeNull();
}

export async function runAiSettingsSaveFlow(api: ApiMockFn, showToast: ReturnType<typeof vi.fn>) {
  await screen.findByText("AI Settings");
  chkLnk(/Review AI suggestions/i, "/audit?tab=needs-you#ai-suggestions");
  expect(screen.getByLabelText("Auto-accept AI suggestions")).toBeDisabled();
  expect(btn(/Save changes/i)).toBeDisabled();
  clkLbl("Enable AI classification"); expect(screen.queryByRole("note")).toBeNull();
  clkBtn(/Reset/i); expect(screen.getByLabelText("Enable AI classification")).not.toBeChecked();
  clkLbl("Enable AI classification"); clkBtn(/Save changes/i);
  await waitOp(api, OPS.AI_PATCH, { body: { enable_ai_classification: true } });
  await waitFor(() => expect(showToast).toHaveBeenCalledWith("AI settings saved", "success"));
}

export function checkChangedChoicesFn(changedChoices: (s: typeof AI_S1 | null, d: typeof AI_S1) => Record<string, unknown>) {
  expect(changedChoices(AI_S1, { ...AI_S1, auto_accept_ai_suggestions: false })).toEqual({ auto_accept_ai_suggestions: false });
  expect(changedChoices(AI_S1, { ...AI_S1, auto_accept_ai_suggestions_active: false })).toEqual({});
  expect(changedChoices(null, AI_S1)).toEqual({ enable_ai_reconciliation: false, enable_ai_classification: true, auto_accept_ai_suggestions: true });
}

export async function runJournalEmptyAndDetails(api: ApiMockFn, renderPage: () => { unmount: () => void }) {
  api.mockRejectedValueOnce(new Error("journal failed")).mockResolvedValue({ items: [] });
  const v0 = renderPage(); await screen.findByText("Failed to load entries");
  clkBtn("Retry loading journal entries"); await screen.findByText("No journal entries yet");
  clkBtn("New Entry"); clkBtn("Mock Submit"); await waitFor(() => expect(api).toHaveBeenCalledTimes(3));
  fireEvent.click(await screen.findByRole("button", { name: "Create First Entry" })); hasTxts("Mock Submit"); v0.unmount();

  const res = journalSampleRes();
  api.mockResolvedValueOnce(res).mockResolvedValueOnce({ items: [] });
  const v1 = renderPage(); await screen.findByText("Draft Entry"); hasTxts(/120\.00/);
  clkTxt("Draft Entry"); expect(await dlgEl("Journal Entry Details")).toHaveTextContent("bank statement");
  clkBtn("Close modal"); await waitFor(() => expect(screen.queryByRole("dialog", { name: "Journal Entry Details" })).toBeNull());
  clkBtn("draft"); await waitOp(api, OPS.JE_LIST, { query: { status_filter: "draft" } }); v1.unmount();
}

export async function runJournalFormBalanceCheck(container: HTMLElement) {
  await screen.findAllByRole("option", { name: "1000 - Cash" });
  hasTxts("✓ Balanced in SGD");
  const a = screen.getAllByPlaceholderText("0.00");
  fireEvent.change(a[0], { target: { value: "100" } }); hasTxts("⚠ Unbalanced or missing FX");
  fireEvent.change(a[1], { target: { value: "100" } }); hasTxts("✓ Balanced in SGD");
  clkBtn("+ Add Line"); expect(screen.getAllByPlaceholderText("0.00")).toHaveLength(3);
  fireEvent.click(container.querySelector("button.btn-ghost") as HTMLButtonElement);
  expect(screen.getAllByPlaceholderText("0.00")).toHaveLength(2);
}

export async function runJournalFormFxSubmit(api: ApiMockFn, container: HTMLElement) {
  await screen.findAllByRole("option", { name: "1010 - USD Bank" });
  chgPh("Description", "USD capital");
  const s = screen.getAllByRole("combobox");
  fireEvent.change(s[0], { target: { value: "a1" } }); fireEvent.change(s[2], { target: { value: "a2" } });
  chgLbl("Line 1 amount", "100"); chgLbl("Line 1 currency", "USD"); chgLbl("Line 1 FX rate", "1.35"); chgLbl("Line 2 amount", "135");
  fireEvent.submit(container.querySelector("form") as HTMLFormElement);
  await waitOp(api, OPS.JE_ADD, { body: expect.objectContaining({ lines: [{ account_id: "a1", direction: "DEBIT", amount: "100.00", currency: "USD", fx_rate: "1.350000" }, { account_id: "a2", direction: "CREDIT", amount: "135.00", currency: "SGD" }] }) });
}

export function checkPickHomeActionCases(pickHomeAction: (wf: WorkflowStatusResponse | null, q: never[]) => unknown) {
  expect(pickHomeAction(makeWorkflowStatus("needs_action"), ACTION_QUEUE_ITEMS as never)).toMatchObject({ title: "2 items need you", href: "/audit?tab=needs-you", firstItem: { title: "oct.csv", href: "/statements/s-oct?from=attention" } });
  expect(pickHomeAction(makeWorkflowStatus("blocked"), [])).toMatchObject({ title: "A blocker holds your reports", href: "/audit" });
  expect(pickHomeAction(makeWorkflowStatus("empty"), [])).toMatchObject({ title: "Upload your first statement", href: "/upload" });
  expect([pickHomeAction(makeWorkflowStatus("ready"), []), pickHomeAction(null, [])]).toEqual([null, null]);
}

export async function runWsSyncAndErrors(renderWs: () => { unmount: () => void }, store: Map<string, string>) {
  const first = renderWs();
  actWrap(() => { window.dispatchEvent(new StorageEvent("storage", { key: "finance-workspace-tabs", newValue: WS_REMOTE })); });
  await waitFor(() => expect(screen.getByTestId("act")).toHaveTextContent("r1"));
  clkBtn("Tog"); await waitFor(() => expect(screen.getByTestId("col")).toHaveTextContent("true")); first.unmount();

  store.clear(); vi.stubGlobal("crypto", {});
  const fb = renderWs(); clkBtn("AddD");
  await waitFor(() => expect(JSON.parse(screen.getByTestId("tabs").textContent ?? "[]")[0]?.id).toBe("4fzzzxj")); fb.unmount();

  vi.stubEnv("NODE_ENV", "development");
  const spy = vi.spyOn(console, "error").mockImplementation(() => {});
  store.set("finance-workspace-tabs", "not-json");
  const bad = renderWs(); await waitFor(() => expect(spy).toHaveBeenCalledWith("Failed to load workspace tabs:", expect.any(Error))); bad.unmount();
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => { throw new Error("save blocked"); }, removeItem: vi.fn() });
  renderWs(); await waitFor(() => expect(spy).toHaveBeenCalledWith("Failed to save workspace tabs:", expect.any(Error)));
  spy.mockRestore(); vi.unstubAllEnvs();
}

function actWrap(fn: () => void) { fn(); }

export async function runApi422AndGuards(
  fetchMock: ReturnType<typeof vi.fn>,
  apiOperation: typeof import("@/lib/api").apiOperation,
  ApiErrorCtor: new (...a: never[]) => Error,
  mockLoc: { href: string; pathname: string },
) {
  fetchMock.mockResolvedValueOnce({ ok: false, status: 422, text: async () => API_422_TEXT });
  const err = await apiOperation(OPS.ACC_ADD, { body: { name: "", type: "ASSET" as never, currency: "SGD" } }).catch((e) => e);
  expect(err).toBeInstanceOf(ApiErrorCtor); expect(err).toMatchObject({ status: 422, errorId: "validation_error", requestId: "req-v1" });
  expect((err as Error).message).toContain("Field required");

  const oldW = (globalThis as { window?: unknown }).window; vi.stubGlobal("window", undefined);
  fetchMock.mockResolvedValueOnce({ ok: false, status: 401, text: async () => "no" });
  await expect(apiOperation(OPS.BASE_CURR)).rejects.toThrow("Authentication required"); vi.stubGlobal("window", oldW);

  Object.defineProperty(window, "location", { configurable: true, get: () => ({ pathname: "/dashboard", set href(_: string) { throw new Error("navigation blocked"); } }) });
  fetchMock.mockResolvedValueOnce({ ok: false, status: 401, text: async () => "unauthorized" });
  await expect(apiOperation(OPS.BASE_CURR)).rejects.toThrow("Authentication required - redirect failed");
  Object.defineProperty(window, "location", { value: mockLoc, writable: true, configurable: true });
}

export async function runQueryCachePolling(
  api: ApiMockFn,
  actFn: (fn: () => Promise<void>) => Promise<void>,
  renderUpload: (c: QueryClient) => { unmount: () => void },
  appClient: QueryClient,
) {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  mockStmtPages(api, [{ items: [stmtShort("s1", "parsing")], total: 1 }, { items: [stmtShort("s1", "parsing")], total: 1 }, { items: [stmtShort("s1", "parsed")], total: 1 }]);
  const v1 = renderUpload(createStaleClient()); await screen.findByText("AI Parsing in Progress");
  await actFn(async () => { await vi.advanceTimersByTimeAsync(3000); });
  await actFn(async () => { await vi.advanceTimersByTimeAsync(3000); });
  await waitFor(() => noTxt("AI Parsing in Progress"));
  await actFn(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(opCalls(api, OPS.STMT_LIST).length).toBe(3); v1.unmount();

  api.mockReset(); api.mockResolvedValue({});
  const v2 = renderUpload(createStaleClient()); await screen.findByText("No statements uploaded yet");
  await actFn(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(opCalls(api, OPS.STMT_LIST).length).toBe(1); v2.unmount();

  vi.useRealTimers(); mockStmtPages(api, [{ items: [], total: 0 }, { items: [stmtShort("s2", "parsing")], total: 1 }]);
  renderUpload(appClient); await screen.findByText("No statements uploaded yet");
  fireEvent.click(screen.getAllByText("UploadMock")[0]); await screen.findByText("s2.pdf");
  expect(appClient.getQueryData(["statements", "list"])).toEqual({ items: [stmtShort("s2", "parsing")], total: 1 });
}

export async function runReview2765Checks(
  api: ApiMockFn,
  renderDetail: () => { unmount: () => void },
) {
  let resolveReview: ((v: unknown) => void) | undefined;
  mockApiMap(api, REVIEW_PENDING_ROUTES((r) => { resolveReview = r; }), {});
  const v2 = renderDetail();
  await screen.findByText("Loading balance verification..."); expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  await waitFor(() => expect(resolveReview).toBeDefined());
  resolveReview!(REVIEW_RESOLVED_PAYLOAD); await waitFor(() => expect(btn("Approve")).toBeInTheDocument()); v2.unmount();
}

export async function runLoginErrorAndSpinner(api: ApiMockFn, setUserMock: ReturnType<typeof vi.fn>, pushMock: ReturnType<typeof vi.fn>, submit: (e: string, p: string, b: string) => void, renderLogin: () => { unmount: () => void }) {
  api.mockRejectedValueOnce(new Error("invalid credentials"));
  const first = renderLogin(); submit("bad@e.com", "password123", "Sign In");
  const a = await alertEl(); expect(a).toHaveAttribute("aria-live", "assertive"); expect(a).toHaveTextContent("invalid credentials");
  expect(setUserMock).not.toHaveBeenCalled(); expect(pushMock).not.toHaveBeenCalled(); first.unmount();

  let resolve!: (v: unknown) => void; api.mockReturnValueOnce(new Promise((r) => { resolve = r; }));
  renderLogin(); submit("a@b.com", "12345678", "Sign In"); await screen.findByText("Processing...");
  resolve(LOGIN_USER("u1", "a@b.com", "tok")); await waitFor(() => expect(screen.queryByText("Processing...")).not.toBeInTheDocument());
}

export async function runNetWorthSeriesStates(
  api: ApiMockFn,
  renderChart: (props: Record<string, unknown>) => { rerender: (ui: ReactElement) => void; unmount: () => void },
  makeEl: (props: Record<string, unknown>) => ReactElement,
  getOpt: () => { tooltip?: { valueFormatter?: (v: number) => string } } | null,
) {
  const Q = { from: "2026-04-01", to: "2026-06-30", includeRestricted: true };
  api.mockResolvedValue(TWO_NET_WORTH_POINTS);
  const v1 = renderChart({ ...Q, currency: "USD" });
  await waitFor(() => expect(screen.getByTestId("net-worth-echarts")).toBeInTheDocument());
  await screen.findByRole("img", { name: "ECharts net worth line chart" });
  expect(getOpt()?.tooltip?.valueFormatter?.(1234)).toContain("1,234.00");
  expect(screen.getByRole("heading", { name: "Daily net worth" })).toBeInTheDocument();
  expect(api).toHaveBeenLastCalledWith(OPS.NW_TS, { query: { from: "2026-04-01", to: "2026-06-30", granularity: "daily", currency: "USD", include_restricted: true } });
  v1.rerender(makeEl({ from: "2025-07-01", to: "2026-06-30", includeRestricted: true }));
  await waitFor(() => expect(screen.getByRole("heading", { name: "Monthly net worth" })).toBeInTheDocument());
  expect(api).toHaveBeenLastCalledWith(OPS.NW_TS, { query: { from: "2025-07-01", to: "2026-06-30", granularity: "monthly", currency: undefined, include_restricted: true } });
  v1.unmount();

  api.mockResolvedValueOnce({ ...TWO_NET_WORTH_POINTS, points: [TWO_NET_WORTH_POINTS.points[0]] });
  const v2 = renderChart(Q); await screen.findByText("At least two net worth points are needed to draw a line."); v2.unmount();
  api.mockRejectedValueOnce(new Error("history failed")); renderChart(Q); await screen.findByText("history failed");
}

export async function runAccountFormCrudChecks(
  api: ApiMockFn,
  onClose: ReturnType<typeof vi.fn>,
  onSuccess: ReturnType<typeof vi.fn>,
  renderModal: (editAccount?: Account) => { unmount: () => void },
) {
  api.mockResolvedValueOnce({ id: "a1" } as never);
  const v1 = renderModal();
  clkBtn("Create Account"); await screen.findByText("Account name is required");
  chgPh("e.g., Cash on Hand", "Cash Box"); chgLbl("Currency *", "USD"); clkBtn("Create Account");
  await waitOp(api, OPS.ACC_ADD, { body: { name: "Cash Box", code: null, type: "ASSET", currency: "USD", description: null } });
  expect(onSuccess).toHaveBeenCalledWith({ id: "a1" }); expect(onClose).toHaveBeenCalledTimes(1); v1.unmount();

  api.mockResolvedValueOnce({ id: "a1" } as never).mockRejectedValueOnce(new Error("update failed"));
  const v2 = renderModal(makeAccount({ id: "a1", name: "Old Name", code: "1000", balance: "0" }));
  fireEvent.change(screen.getByDisplayValue("Old Name"), { target: { value: "Renamed" } });
  fireEvent.change(screen.getByDisplayValue("1000"), { target: { value: "1100" } });
  clkBtn("Save Changes");
  await waitOp(api, OPS.ACC_UPD, { path: { account_id: "a1" }, body: { name: "Renamed", code: "1100", is_active: true } });
  clkBtn("Save Changes"); await screen.findByText("update failed"); v2.unmount();

  api.mockRejectedValueOnce(new Error("create failed")); renderModal();
  chgPh("e.g., Cash on Hand", "Cash"); clkBtn("Create Account"); await screen.findByText("create failed");
}

export async function runCoverage2763BannerCheck(testUrlFn: () => string) {
  expect(await screen.findByTestId("report-latest-statement-banner")).toHaveTextContent("Latest statement ends Mar 31, 2025, before this period.");
  clkBtn("Jump to Mar 31, 2025"); expect(testUrlFn()).toBe("/reports?end=2025-03-31");
  expect(await screen.findByTestId("report-coverage-note")).toHaveTextContent("Starts Mar 1, 2025: DBS USD and Wise EUR have no opening balance before this date.");
}

export async function runAttentionQueueRetry(api: ApiMockFn) {
  await screen.findByText("Couldn't load the items that need confirmation"); hasTxts("offline");
  clkBtn("Retry");
  expect(await screen.findByRole("link", { name: /late\.pdf/ })).toHaveAttribute("href", "/statements/late?from=attention");
  noTxt("Couldn't load the items that need confirmation");
  expect([OPS.STMT_LIST, OPS.REC_STATS, OPS.REC_PEND].map((id) => opCalls(api, id).length)).toEqual([2, 1, 1]);
}

export async function runApiFnWrappersCheck(
  callStream: (op: never, req: never) => Promise<{ sessionId: string | null }>,
  callUpload: (op: never, req: never) => Promise<unknown>,
  callDownload: (op: never, req: never) => Promise<unknown>,
) {
  vi.stubGlobal("fetch", makeFetchMock(200, "", { "X-Session-Id": "sess-1" }));
  expect((await callStream(OPS.CHAT_POST as never, { body: { message: "hi" } } as never)).sessionId).toBe("sess-1");
  const fd = new FormData(); fd.append("file", new Blob(["data"]), "test.pdf");
  vi.stubGlobal("fetch", makeFetchMock(200, { uploaded: true }));
  expect(await callUpload(OPS.UPL as never, { body: fd } as never)).toEqual({ uploaded: true });
  const csv = new Blob(["ok"], { type: "text/csv" });
  vi.stubGlobal("fetch", makeFetchMock(200, csv, { "content-disposition": 'attachment; filename="cash-flow.csv"' }));
  expect(await callDownload(OPS.EXP as never, { query: {} } as never)).toMatchObject({ blob: csv, filename: "cash-flow.csv" });
}

export function checkAdvisorBriefCardsDom() {
  expect(screen.getByLabelText("Advisor Brief")).toBeInTheDocument();
  hasTxts("Readiness blocker", "Ready facts", "Needs review", "Refresh market data", "Advisor signal", "b-blocked", "l-blocked", "Workflow Status", "source unavailable");
  const cards = screen.getAllByTestId(/advisor-brief-card-/);
  expect(cards.map((c) => within(c).getByRole("link", { name: "Open next action" }).getAttribute("href"))).toEqual(["/reports?tab=package", "/reports", "/upload", "/portfolio?panel=prices", "/portfolio"]);
  expect(within(cards[0]).getByRole("link", { name: "Ask about this" })).toHaveAttribute("href", expect.stringContaining("/chat?prompt="));
}

export const ADVISOR_SUGGESTIONS_5 = [
  { basis: "b-blocked", confidence_tier: "blocked" as const, source_refs: ["workflow.status", "report_package.readiness"], limitation: "l-blocked", next_action_href: "/reports/package" },
  { basis: "b-deterministic", confidence_tier: "deterministic" as const, source_refs: ["reports.balance_sheet"], limitation: "l-deterministic", next_action_href: "/reports" },
  { basis: "b-review_required", confidence_tier: "review_required" as const, source_refs: ["reconciliation.stats"], limitation: "l-review_required", next_action_href: "/review" },
  { basis: "b-stale", confidence_tier: "stale" as const, source_refs: ["market_data.freshness"], limitation: "l-stale", next_action_href: "/portfolio?panel=prices" },
  { basis: "b-unsupported", confidence_tier: "unsupported" as const, source_refs: [], limitation: "l-unsupported", next_action_href: "/assets?filter=manual" },
];

export const mockAttnOps = (api: ApiMockFn, st: unknown[] = [], stats = ATTN_OK) =>
  mockApiMap(api, { [OPS.STMT_LIST]: { items: st, total: st.length }, [OPS.REC_STATS]: stats, [OPS.REC_PEND]: { items: [], total: 0 } }, null);

export async function runNetWorthCacheScope(api: ApiMockFn, renderEl: (inc: boolean) => ReactElement) {
  api.mockResolvedValue(TWO_NET_WORTH_POINTS);
  const w = clientWrapper(createStaleClient());
  const f = render(renderEl(true), { wrapper: w }); await waitFor(() => expect(screen.getByTestId("net-worth-echarts")).toBeInTheDocument()); f.unmount();
  const r = render(renderEl(true), { wrapper: w }); await waitFor(() => expect(screen.getByTestId("net-worth-echarts")).toBeInTheDocument()); expect(api).toHaveBeenCalledTimes(1); r.unmount();
  render(renderEl(false), { wrapper: w }); await waitFor(() => expect(api).toHaveBeenCalledTimes(2));
  expect(api.mock.calls.map(([, req]) => (req as { query: { include_restricted: boolean } }).query.include_restricted)).toEqual([true, false]);
}

export function checkPortfolioScheduleDom(c: HTMLElement) {
  hasTxts("Provider: Interactive Brokers, Yahoo Finance", "Manual override: NVDA (2025-03-31)");
  expect(c.textContent).not.toContain("yahoo_finance");
  expect(c.textContent).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
}

export async function runAiToggleAndErrorFlows(
  api: ApiMockFn,
  renderPanel: () => { unmount: () => void },
) {
  mockAiSettingsRoutes(api, AI_S1, { ...AI_S1, auto_accept_ai_suggestions: false, auto_accept_ai_suggestions_active: false });
  const v1 = renderPanel(); await waitFor(() => expect(screen.getByLabelText("Auto-accept AI suggestions")).toBeChecked());
  clkLbl("Auto-accept AI suggestions"); clkBtn(/Save changes/i);
  await waitOp(api, OPS.AI_PATCH, { body: { auto_accept_ai_suggestions: false } }); v1.unmount();
  mockAiSettingsRoutes(api, AI_S2, { ...AI_S2, enable_ai_reconciliation: true });
  const v2 = renderPanel(); await screen.findByText("AI Settings");
  clkLbl("Enable AI reconciliation"); clkBtn(/Save changes/i);
  await waitOp(api, OPS.AI_PATCH, { body: { enable_ai_reconciliation: true } }); v2.unmount();

  mockAiSettingsRoutes(api, AI_SETTINGS_DEFAULT, () => { throw new Error("Save failed"); });
  const v3 = renderPanel(); await screen.findByText("AI Settings");
  clkLbl("Enable AI classification"); clkBtn(/Save changes/i);
  await findAlert("Save failed"); expect(screen.getByLabelText("Enable AI classification")).toBeChecked(); v3.unmount();
  api.mockRejectedValue(new Error("Load failed")); const v4 = renderPanel(); await findAlert("Load failed"); v4.unmount();
}

export async function runJournalFormPostAndFail(
  api: ApiMockFn,
  renderOpen: () => { container: HTMLElement; unmount: () => void },
) {
  api.mockResolvedValueOnce({ items: JOURNAL_ACCOUNTS }).mockResolvedValueOnce({ id: "je-post" }).mockResolvedValueOnce({});
  const v2 = renderOpen(); await screen.findAllByRole("option", { name: "1000 - Cash" });
  clkBtn("Create Draft"); await screen.findByText("Memo is required");
  fireEvent.change(v2.container.querySelector("input[name='entry_date']") as HTMLInputElement, { target: { value: "2026-02-02" } });
  chgPh("Description", "Immediate post"); fillJournalLines("88"); clkLbl("Post transaction immediately");
  fireEvent.submit(v2.container.querySelector("form") as HTMLFormElement);
  await waitFor(() => expect(opCalls(api, OPS.JE_POST).length).toBeGreaterThan(0)); v2.unmount();

  api.mockResolvedValueOnce({ items: JOURNAL_ACCOUNTS }).mockRejectedValueOnce(new Error("create entry failed"));
  const v3 = renderOpen(); await screen.findAllByRole("option", { name: "1000 - Cash" });
  chgPh("Description", "Fail"); fillJournalLines("50"); fireEvent.submit(v3.container.querySelector("form") as HTMLFormElement);
  await screen.findByText("create entry failed"); v3.unmount();
}

export async function runQueryCacheDedupFlow(api: ApiMockFn, pairUi: ReactElement, uploadUi: ReactElement, queueUi: ReactElement) {
  mockStmtPages(api, [{ items: [stmtShort("s1", "parsed")], total: 1 }]);
  const v1 = render(pairUi, { wrapper: clientWrapper(createStaleClient()) });
  await screen.findByRole("region", { name: "Needs attention" });
  await within(screen.getByTestId("needs-confirmation-queue")).findByText("5 unmatched transactions");
  expect([OPS.STMT_LIST, OPS.REC_STATS, OPS.REC_PEND, OPS.REC_UNM].map((op) => opCalls(api, op).length)).toEqual([1, 1, 1, 1]);
  v1.unmount();

  api.mockClear(); mockStmtPages(api, [{ items: [stmtShort("s1", "approved")], total: 1 }]);
  const w = clientWrapper(createStaleClient()), u = render(uploadUi, { wrapper: w });
  await screen.findByText("s1.pdf"); u.unmount();
  render(queueUi, { wrapper: w }); await screen.findByText("5 unmatched transactions");
  expect(opCalls(api, OPS.STMT_LIST).length).toBe(1);
}

export async function runOpeningBalInvalidateAndErrors(
  api: ApiMockFn,
  coverageKey: readonly unknown[],
  renderModal: (props: { accounts: Account[]; onClose: () => void; onSuccess: () => void }, wrapper?: ReturnType<typeof clientWrapper>) => { unmount: () => void },
) {
  api.mockResolvedValueOnce({ id: "opening-entry" });
  const c = new QueryClient(), keys = [[...coverageKey, "2026-10-22"], ...OB_INVALIDATION_KEYS];
  for (const k of keys) c.setQueryData(k, { seeded: true });
  const onSuccess = vi.fn();
  const v0 = renderModal({ accounts: OPENING_ACCOUNTS, onClose: vi.fn(), onSuccess }, clientWrapper(c));
  chgLbl("As-of date *", "2026-06-30"); chgLbl("Opening balance for Cash", "100.00"); clkBtn("Record opening balances");
  await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
  expect(keys.map((k) => c.getQueryState(k)?.isInvalidated)).toEqual([true, true, true, true]); v0.unmount();

  const v1 = renderModal({ accounts: [], onClose: vi.fn(), onSuccess: vi.fn() });
  hasTxts("Create an asset, liability, or equity account first, then set its opening balance.");
  expect(btn("Record opening balances")).toBeDisabled(); v1.unmount();

  api.mockRejectedValueOnce(new Error("Account has activity before this date"));
  const onClose = vi.fn(); renderModal({ accounts: OPENING_ACCOUNTS, onClose, onSuccess: vi.fn() });
  chgLbl("As-of date *", "2026-01-01"); chgLbl("Opening balance for Cash", "100"); clkBtn("Record opening balances");
  await screen.findByText("Account has activity before this date"); expect(onClose).not.toHaveBeenCalled();
}

export async function runBannerSilentAndFallback(api: ApiMockFn, renderBanner: () => { container: HTMLElement; unmount: () => void }) {
  mockApiMap(api, ACTION_CLEAR_ROUTES, null);
  const v3 = renderBanner(); await waitFor(() => expect(api).toHaveBeenCalledWith(OPS.REC_PEND, expect.anything()));
  await waitFor(() => expect(v3.container).toBeEmptyDOMElement()); v3.unmount();
  mockApiMap(api, { [OPS.STMT_LIST]: () => Promise.reject(new Error("offline")) }, null);
  const v4 = renderBanner(); await new Promise((r) => setTimeout(r, 20));
  expect(v4.container).toBeEmptyDOMElement(); v4.unmount();
  mockApiMap(api, { [OPS.WF]: makeWorkflowStatus("needs_action", "") }, null);
  renderBanner(); const b = await screen.findByRole("region", { name: "Needs attention" });
  expect(within(b).getAllByText("Review the required action so automation can continue.")).toHaveLength(1);
  expect(within(b).getByRole("link", { name: "Review required" })).toHaveAttribute("href", "/audit");
}

export async function runSidebarTabsChecks(
  renderTabs: () => { unmount: () => void },
  setPath: (p: string) => void,
  setWs: (patch: Record<string, unknown>) => void,
  addTab: ReturnType<typeof vi.fn>,
  setActiveTab: ReturnType<typeof vi.fn>,
  removeTab: ReturnType<typeof vi.fn>,
  push: ReturnType<typeof vi.fn>,
) {
  setPath("/reports"); const first = renderTabs(); await waitFor(() => expect(addTab).toHaveBeenCalled());
  clkTxt("Dashboard"); expect(setActiveTab).toHaveBeenCalledWith("tab-1");
  fireEvent.click(screen.getByLabelText("Close Dashboard tab")); expect(removeTab).toHaveBeenCalledWith("tab-1"); hasTxts("Open Tabs"); first.unmount();
  setPath("/dashboard"); setWs(SIDEBAR_EMPTY_WS); const empty = renderTabs(); hasTxts("No tabs open"); empty.unmount();
  setWs(SIDEBAR_TWO_TABS_WS); renderTabs(); checkTabsKeyboard(push, setActiveTab);
}

export async function runOverflowCheckAll(api: ApiMockFn, bsEl: ReactElement, holdEl: ReactElement, unmEl: ReactElement) {
  mockApiMap(api, { [OPS.BS]: OVERFLOW_BS }, { currency: "SGD", granularity: "monthly", points: [] });
  const v1 = render(bsEl);
  const amt = await screen.findByRole("button", { name: "View source transactions for Margin Cash Account With Very Long Label" });
  expect(amt).toHaveClass("whitespace-nowrap", "tabular-nums"); expect(amt.parentElement).toHaveClass("shrink-0"); checkOverflowBsDom(); v1.unmount();
  const v2 = render(holdEl); checkOverflowHoldingsDom(v2.container); v2.unmount();
  api.mockResolvedValueOnce(OVERFLOW_UNMATCHED).mockResolvedValueOnce({ items: [], total: 0 });
  const v3 = render(unmEl); await waitFor(() => expect(screen.getAllByText("-SGD 980.50")).toHaveLength(2));
  v3.container.querySelectorAll(".card").forEach((c) => expect(c).toHaveClass("min-w-0", "overflow-hidden"));
  expect(screen.getAllByText("-SGD 980.50")[0]).toHaveClass("whitespace-nowrap", "tabular-nums");
}

export async function runHomeCoverageBounds(api: ApiMockFn, renderHome: () => { unmount: () => void }, setUrl: (u: string) => void) {
  const bsDates = () => opCalls(api, OPS.BS).map(([, r]) => ((r ?? {}) as { query?: Record<string, unknown> }).query?.as_of_date).sort();
  const v1 = renderHome(), bal = await screen.findByTestId("cockpit-card-balance-sheet");
  await waitFor(() => expect(within(bal).getByText("Change in period").nextElementSibling).toHaveTextContent("+SGD 1,500"));
  expect(within(bal).getByTestId("change-in-period-basis")).toHaveTextContent("Jul 1, 2026, when your cash opening balances are complete.");
  checkCoveragePeriodNote("Jul 1, 2026 – Oct 22, 2026", true); chkLnk("Add an opening balance", "/settings?tab=accounts");
  expect(bsDates()).toEqual(["2026-07-01", "2026-10-22"]); v1.unmount();
  api.mockClear(); setUrl("/?period=All&end=2026-10-22"); renderHome();
  await waitFor(() => checkCoveragePeriodNote("Jul 1, 2026 – Oct 22, 2026", true));
}

export async function runHomeCoverageJump(renderHome: () => { unmount: () => void }, setBounds: (s: string | null, l: string | null) => void, setUrl: (u: string) => void, testUrlFn: () => string) {
  setBounds(null, null); const v1 = renderHome();
  await waitFor(() => checkCoveragePeriodNote("Nov 1, 2025 – Oct 22, 2026", false)); expect(screen.queryByTestId("report-coverage-note")).toBeNull(); v1.unmount();
  setBounds("2025-01-01", "2025-03-31"); setUrl("/?end=2026-10-22"); renderHome();
  const b = await screen.findByTestId("report-latest-statement-banner"); expect(b).toHaveTextContent("Latest statement ends Mar 31, 2025, before this period.");
  fireEvent.click(within(b).getByRole("button", { name: /Jump to Mar 31, 2025/i })); expect(testUrlFn()).toBe("/?end=2025-03-31");
}

export async function runFirstRunAndWarnings2763(warnEl: ReactElement, modalEl: ReactElement, dismissedKey: string) {
  const v2 = render(warnEl); await findAlert("DBS USD: No opening balance recorded before 2025-03-01.");
  expect(screen.getAllByRole("listitem")).toHaveLength(2); v2.unmount();
  const first = render(modalEl); expect((screen.getByTestId("provider-advanced-settings") as HTMLDetailsElement).open).toBe(false);
  clkBtn(/Cancel/i); expect(window.localStorage.getItem(dismissedKey)).toBe("true"); first.unmount();
  expect(render(modalEl).container).toBeEmptyDOMElement();
}

export async function runAccountFormReopen(api: ApiMockFn, renderHost: (open: boolean, name: string, type: string) => ReactElement) {
  api.mockResolvedValue({ id: "generated-account" } as never);
  const { rerender } = render(renderHost(false, "", "ASSET"));
  for (const type of ["ASSET", "INCOME", "EXPENSE"]) {
    const name = `Generated ${type}`; rerender(renderHost(true, name, type));
    expect(screen.getByPlaceholderText("e.g., Cash on Hand")).toHaveValue(name); clkBtn("Create Account");
    await waitFor(() => expect(api).toHaveBeenLastCalledWith(OPS.ACC_ADD, { body: { name, code: null, type, currency: "SGD", description: null } }));
    rerender(renderHost(false, name, type));
  }
  expect(api).toHaveBeenCalledTimes(3);
}

export async function runLoginSubmitFlows(api: ApiMockFn, setUserMock: ReturnType<typeof vi.fn>, pushMock: ReturnType<typeof vi.fn>, trackFn: unknown, signupEv: unknown, renderLogin: () => { unmount: () => void }) {
  const sub = (e: string, p: string, b: string) => { chgLbl("Email Address", e); chgLbl("Password", p); clkBtn(b); };
  api.mockResolvedValueOnce(LOGIN_USER("u1", "u@e.com", "t1"));
  const v1 = renderLogin(); sub("u@e.com", "password123", "Sign In");
  await waitOp(api, OPS.LOGIN, { body: { email: "u@e.com", password: "password123" } });
  expect(setUserMock).toHaveBeenCalledWith("u1", "u@e.com"); expect(pushMock).toHaveBeenCalledWith("/");
  expect(vi.mocked(trackFn as never)).not.toHaveBeenCalledWith(signupEv); v1.unmount();

  api.mockResolvedValueOnce(LOGIN_USER("u2", "n@e.com", "t2"));
  renderLogin(); fireEvent.click(screen.getByTestId("auth-mode-toggle-register")); sub("n@e.com", "password123", "Create Account");
  await waitOp(api, OPS.REG, { body: { email: "n@e.com", password: "password123" } });
  await waitFor(() => expect(vi.mocked(trackFn as never)).toHaveBeenCalledWith(signupEv));
}

export function checkEnvelope2765Props() {
  return {
    requiresEnvelopeConfirmation: true,
    requiresOtherSourceReview: false,
    sourceMissingFacts: [] as string[],
    missingFactLabels: {} as Record<string, string>,
    custodyAccounts: [{ id: "acc-1", name: "DBS", currency: "SGD" }],
    onConfirm: () => {},
    isPending: false,
  };
}

export function checkReadReportFilters2763(
  readReportFilters: (params: URLSearchParams, now: Date, cov: typeof COV_2763) => ReportFilters,
) {
  expect(readReportFilters(new URLSearchParams("period=All"), new Date(2026, 9, 27), COV_2763).coverageLimitingAccounts).toEqual(["DBS USD", "Wise EUR"]);
  expect(readReportFilters(new URLSearchParams("end=2025-03-31"), new Date(2026, 9, 27), COV_2763).opensAtCoverageStart).toBe(true);
}

export async function runLlmAddAndDeleteErr(api: ApiMockFn, showToast: ReturnType<typeof vi.fn>, renderPanel: () => { unmount: () => void }) {
  mockLlmRoutes(api, { [OPS.LLM_PROV_DEL]: () => { throw new Error("Delete boom"); } });
  const v2 = renderPanel(); fireEvent.click(await screen.findByRole("button", { name: /Delete provider OpenRouter/i }));
  fireEvent.click(await screen.findByRole("button", { name: "Delete provider" })); await findAlert("Delete boom"); v2.unmount();
  mockLlmRoutes(api); renderPanel(); await screen.findByText("LLM Models");
  for (const b of [/Close/i, /Cancel/i]) { clkBtn(/Add provider/i); clkBtn(b); expect(screen.queryByLabelText("API key")).toBeNull(); }
  clkBtn(/Add provider/i); chgLbl("Label", "New"); chgLbl("API key", "key"); clkBtn(/^Add provider$/i);
  await waitOp(api, OPS.LLM_PROV_ADD, expect.objectContaining({ body: expect.objectContaining({ label: "New", api_key: "key" }) }));
  await waitFor(() => expect(showToast).toHaveBeenCalledWith("Provider added", "success"));
}

export const pkgHookMock = (mockedPkg: (...a: unknown[]) => unknown) =>
  async (o: <T>() => Promise<T>) => ({
    ...(await o<typeof import("@/hooks/usePersonalReportPackage")>()),
    usePersonalReportPackage: (...a: unknown[]) => mockedPkg(...a),
    generatePackageSnapshot: vi.fn(),
    invalidateReportPackageQueries: vi.fn(),
  });

export async function runCashFlowAndReview2765(
  api: ApiMockFn,
  reportsEl: ReactElement,
  renderDetail: () => { unmount: () => void },
  renderEnv: (d: typeof DRAFT_2765, onDraftChange: (fn: (prev: typeof DRAFT_2765) => typeof DRAFT_2765) => void) => ReactElement,
) {
  api.mockResolvedValue(CASH_FLOW_BRIDGE_PAYLOAD);
  const v1 = render(reportsEl);
  expect(await screen.findByLabelText("Cash reconciliation")).toHaveTextContent(/Includes.*1,250\.00.*unclassified cash movement/i);
  v1.unmount();
  await runReview2765Checks(api, renderDetail);
  let d = { ...DRAFT_2765 };
  render(renderEnv(d, (fn) => { d = fn(d); }));
  clkBtn("Use standard confirmation note");
  expect(d.rationale).toBe("Confirmed statement header and opening/closing balances against source file");
}

export async function runCoverage2763Full(
  api: ApiMockFn,
  readReportFilters: (params: URLSearchParams, now: Date, cov: typeof COV_2763) => ReportFilters,
  hostEl: ReactElement,
  setUrl: (u: string) => void,
  testUrlFn: () => string,
) {
  checkReadReportFilters2763(readReportFilters);
  mockApiMap(api, COV_2763_ROUTES);
  setUrl("/reports");
  const v1 = render(hostEl);
  await runCoverage2763BannerCheck(testUrlFn);
  v1.unmount();
}

export const LLM_EMPTY_ROUTES = {
  list_providers_llm_providers_get: { providers: [] },
  get_catalog_llm_catalog_get: { models: [] },
  get_scenes_llm_scenes_get: { bindings: [] },
};

export const SIDEBAR_HIDDEN_LINKS = [/Advanced/i, /Journal/i, /^Reconciliation$/i, /^Accounts$/i, /^Upload$/i, /AI Settings/i];
export const SIDEBAR_NAV_LINKS = [[/^Chat$/i, "/chat"], [/^Audit$/i, "/audit"], [/^More$/i, "/more"], [/Finance Report home/i, "/"]] as const;
export const WORKSPACE_LABEL_CASES = [
  ["/custom-page-name", "Custom Page Name"],
  ["/portfolio", "Portfolio"],
  ["/statements/3f2b8c1e-9d4a-4e57-8a60-1c2d3e4f5a6b", "Statement"],
] as const;

export const HUMANIZE_BADGES = [
  ["AUTO-ASSET", "Auto-created"], ["SYS-PROCESSING", "System clearing"],
  ["AUTO-EQUITY-OPENING", "Opening equity"], ["AUTO-BANK", "Auto bank"], ["1001", "1001"],
] as const;

export const HUMANIZE_TEXTS = [
  ["1 statement(s) waiting for review", "1 statement waiting for review"],
  ["2 statement(s) waiting for review", "2 statements waiting for review"],
  ["Market data is stale for 1 observed scope(s).", "Market data is stale for 1 observed scope."],
  ["Workflow has 2 action-required event(s).", "Workflow has 2 action-required events."],
  ["Pending statement(s) need attention", "Pending statements need attention"],
  ["Unproven package input: 3", "Unconfirmed statement entries: 3"],
] as const;

export const OTEL_SCRUB_CASES = [
  ["https://app.example.com/reports?email=a@b.com#frag", "https://app.example.com/reports"],
  ["https://app.example.com/reports", "https://app.example.com/reports"],
  ["/accounts/42?token=secret", "/accounts/42"],
  ["/accounts/42#balance", "/accounts/42"],
  ["/accounts/42", "/accounts/42"],
  ["", ""],
] as const;

export const OTEL_RAW_ATTRS = {
  "user.email": "a@b.com", "txn.amount": 100, "bank.account_number": "123",
  Authorization: "Bearer x", "session.cookie": "c",
  "http.url": "https://x.com/p?q=1#h", "document.url": "https://x.com/d?a=b",
  "http.target": 8080, missing: undefined, empty: null, "ok.flag": true,
};

export const OTEL_ENV = {
  NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT: OTEL_CFG.endpoint,
  NEXT_PUBLIC_DEPLOYMENT_ENVIRONMENT: "staging",
  NEXT_PUBLIC_GIT_SHA: "abc123",
};

export const CHAT_GROUNDED_HEADERS = {
  "X-Advisor-Metadata": JSON.stringify({
    citations: [{ label: "Balance Sheet", source_ref: "balance_sheet.total_equity", confidence_tier: "TRUSTED", href: "/reports/balance-sheet" }],
    actions: [{ kind: "reconciliation_review", label: "Review 2", href: "/reconciliation?tab=review-queue", count: 2 }],
  }),
};

export const COCKPIT_EXPECTED_ROWS = [
  "View source transactions for IBKR Portfolio",
  "View source transactions for DBS Multiplier",
  "View source transactions for Visa Infinite",
  "View source transactions for Transfers in transit",
];

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
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
    text: () =>
      Promise.resolve(typeof body === "string" ? body : JSON.stringify(body)),
    json: () => Promise.resolve(body),
    blob: () =>
      Promise.resolve(body instanceof Blob ? body : new Blob([String(body)])),
    headers: {
      get: (name: string) =>
        headers[name] ?? headers[name.toLowerCase()] ?? null,
    },
  });
const makeAccount = (overrides: Partial<Account> = {}): Account => ({
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
const makeStats = (
  overrides: Partial<ReconciliationStatsResponse> = {},
): ReconciliationStatsResponse => ({
  total_transactions: 100,
  matched_transactions: 80,
  unmatched_transactions: 5,
  pending_review: 3,
  auto_accepted: 70,
  match_rate: 80,
  score_distribution: {},
  ...overrides,
});
const makeBalanceSheet = (overrides: Record<string, unknown> = {}) => ({
  as_of_date: "2026-03-31",
  currency: "SGD",
  assets: [
    {
      account_id: "acc-cash",
      name: "DBS Multiplier",
      type: "ASSET",
      amount: "12000",
    },
  ],
  liabilities: [
    {
      account_id: "acc-card",
      name: "Visa Infinite",
      type: "LIABILITY",
      amount: "2000",
    },
  ],
  equity: [],
  total_assets: "40000",
  total_liabilities: "2000",
  total_equity: "38000",
  equation_delta: "0",
  is_balanced: true,
  ...overrides,
});
const makeIncomeStatement = (overrides: Record<string, unknown> = {}) => ({
  start_date: "2026-01-01",
  end_date: "2026-03-31",
  currency: "SGD",
  income: [
    {
      account_id: "acc-salary",
      name: "Base Salary",
      type: "INCOME",
      amount: "9000",
    },
  ],
  expenses: [
    {
      account_id: "acc-rent",
      name: "Apartment Rent",
      type: "EXPENSE",
      amount: "4500",
    },
  ],
  total_income: "9000",
  total_expenses: "4500",
  net_income: "4500",
  trends: [],
  ...overrides,
});
const makeCashFlow = (overrides: Record<string, unknown> = {}) => ({
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
const clientWrapper = (client: QueryClient) => {
  const Wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client }, children);
  return Wrapper;
};

export const opCalls = (
  mockedFn: { mock: { calls: unknown[][] } },
  op: string,
) => mockedFn.mock.calls.filter(([id]) => id === op);

export function mockApiMap(
  mockedFn: { mockImplementation: (fn: never) => unknown },
  routes: Record<
    string,
    | unknown
    | ((req: {
        query?: Record<string, unknown>;
        path?: Record<string, unknown>;
        body?: unknown;
      }) => unknown)
  >,
  fallback: unknown = { items: [], total: 0 },
) {
  mockedFn.mockImplementation(((
    op: string,
    req?: {
      query?: Record<string, unknown>;
      path?: Record<string, unknown>;
      body?: unknown;
    },
  ) => {
    if (op in routes) {
      const val = routes[op];
      return Promise.resolve(
        typeof val === "function"
          ? (val as (r: unknown) => unknown)(req ?? {})
          : val,
      );
    }
    return Promise.resolve(
      typeof fallback === "function"
        ? (fallback as (o: string, r: unknown) => unknown)(op, req ?? {})
        : fallback,
    );
  }) as never);
}

export const makeStreamRes = (text: string, headers?: HeadersInit): Response =>
  new Response(
    new ReadableStream({
      start(c) {
        const enc = new TextEncoder();
        c.enqueue(enc.encode("event: meta\ndata: {}\n\n"));
        c.enqueue(enc.encode(`event: delta\ndata: ${JSON.stringify({ text })}\n\n`));
        c.enqueue(enc.encode("event: done\ndata: {}\n\n"));
        c.close();
      },
    }),
    { headers },
  );

export const CHAT_SUGGESTIONS = {
  suggestions: ["How is cash flow?"],
  structured_suggestions: [
    {
      basis: "Report package is blocked by one review-required item.",
      confidence_tier: "blocked",
      source_refs: ["workflow.status", "report_package.readiness"],
      limitation: "Review the blocker before relying on this report.",
      next_action_href: "/reports/package",
    },
  ],
};

export const CHAT_EMPTY_HISTORY = {
  sessions: [
    { id: "sess-1", title: "Cash flow review", message_count: 0, messages: [] },
  ],
};

export const CHAT_TABLE_HISTORY = {
  sessions: [
    {
      id: "sess-1",
      title: "Review",
      message_count: 2,
      messages: [
        { id: "m1", role: "user", content: "What is my net worth?" },
        {
          id: "m2",
          role: "assistant",
          content:
            "Summary:\n| Metric | Value |\n|---|---|\n| Cash | **$5,000** |\nThe above analysis is for reference only.",
        },
      ],
    },
  ],
};

export const AI_SETTINGS_DEFAULT = {
  enable_ai_reconciliation: true,
  enable_ai_classification: false,
  auto_accept_ai_suggestions: true,
  auto_accept_ai_suggestions_active: false,
};

export const mockAiSettingsRoutes = (
  api: ApiMockFn,
  getVal = AI_SETTINGS_DEFAULT,
  patchVal: unknown = AI_SETTINGS_DEFAULT,
) =>
  mockApiMap(api, {
    get_current_user_settings_users_me_settings_get: getVal,
    patch_current_user_settings_users_me_settings_patch: patchVal,
  });
const makeJournalEntry = (
  id: string,
  status: string,
  memo: string,
  amount = 200,
  source_type = "manual",
) => ({
  id,
  memo,
  entry_date: "2026-01-01",
  status,
  source_type,
  created_at: "2026-01-01T00:00:00Z",
  lines: [
    {
      id: `${id}-1`,
      account_id: "a1",
      direction: "DEBIT",
      amount,
      currency: "SGD",
      description: "d",
    },
    {
      id: `${id}-2`,
      account_id: "a2",
      direction: "CREDIT",
      amount,
      currency: "SGD",
      description: "c",
    },
  ],
});

export const OPENING_ACCOUNTS = [
  makeAccount({ id: "a1", name: "Cash", type: "ASSET" }),
  makeAccount({ id: "a2", name: "Credit Card", type: "LIABILITY" }),
  makeAccount({ id: "a3", name: "Salary", type: "INCOME" }),
  makeAccount({ id: "a4", name: "Closed", type: "ASSET", is_active: false }),
];

export function discoverPageRoutes(
  dir: string,
  segments: string[] = [],
): string[] {
  const found: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      const isGroup = entry.name.startsWith("(") && entry.name.endsWith(")");
      found.push(
        ...discoverPageRoutes(
          path.join(dir, entry.name),
          isGroup ? segments : [...segments, entry.name],
        ),
      );
    } else if (entry.name === "page.tsx") {
      found.push("/" + segments.join("/"));
    }
  }
  return found;
}
const OTEL_CFG = {
  endpoint: "https://otel.zitian.party/v1/traces",
  environment: "staging",
  serviceVersion: "abc123",
};
const fakeOtelProvider = () => {
  const recordException = vi.fn();
  const setAttribute = vi.fn();
  const end = vi.fn();
  return {
    recordException,
    setAttribute,
    end,
    provider: {
      getTracer: () => ({
        startSpan: () => ({ setAttribute, recordException, end }),
      }),
    },
  };
};

export function withDefinedProps(
  defs: [object, string, PropertyDescriptor][],
  fn: () => void,
) {
  const orig = defs.map(
    ([t, k]) => [t, k, Object.getOwnPropertyDescriptor(t, k)] as const,
  );
  try {
    for (const [t, k, d] of defs)
      Object.defineProperty(t, k, { configurable: true, ...d });
    fn();
  } finally {
    for (const [t, k, d] of orig) if (d) Object.defineProperty(t, k, d);
  }
}

export const makeCoverageRoutes = (
  getStart: () => string | null,
  getLatest: () => string | null = () => null,
) => ({
  report_coverage_reports_coverage_get: (r: {
    query?: Record<string, unknown>;
  }) => ({
    as_of_date: r.query?.as_of_date,
    coverage_start: getStart(),
    limiting_accounts: getStart() ? ["OCBC Bank"] : [],
    latest_statement_end: getLatest(),
  }),
  balance_sheet_reports_balance_sheet_get: (r: {
    query?: Record<string, unknown>;
  }) =>
    makeBalanceSheet({
      as_of_date: String(r.query?.as_of_date),
      total_assets: r.query?.as_of_date === getStart() ? "3500" : "5000",
      total_liabilities: "1000",
    }),
  income_statement_reports_income_statement_get: makeIncomeStatement({
    total_income: "3000",
    total_expenses: "1500",
    net_income: "1500",
  }),
  cash_flow_reports_cash_flow_get: makeCashFlow({
    summary: {
      operating_activities: "1500",
      investing_activities: "0",
      financing_activities: "0",
      net_cash_flow: "1500",
      beginning_cash: "0",
      ending_cash: "1500",
    },
  }),
  reconciliation_stats_reconciliation_stats_get: makeStats({
    total_transactions: 5,
    matched_transactions: 5,
    unmatched_transactions: 0,
    pending_review: 0,
    auto_accepted: 5,
    match_rate: 100,
  }),
  get_available_currencies_reports_currencies_get: ["SGD"],
  get_base_currency_users_me_settings_base_currency_get: {
    base_currency: "SGD",
  },
});

export const btn = (name: string | RegExp) =>
  screen.getByRole("button", { name });
const lnk = (name: string | RegExp) => screen.getByRole("link", { name });
export const clkBtn = (name: string | RegExp) => fireEvent.click(btn(name));
export const clkTxt = (text: string | RegExp) =>
  fireEvent.click(screen.getByText(text));
const clkLbl = (label: string | RegExp) =>
  fireEvent.click(screen.getByLabelText(label));
export const chgLbl = (label: string | RegExp, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
const alertEl = () => screen.findByRole("alert");
const dlgEl = (name?: string | RegExp) =>
  name ? screen.findByRole("dialog", { name }) : screen.findByRole("dialog");
export const hasTxts = (...ts: (string | RegExp)[]) => {
  for (const t of ts) expect(screen.getByText(t)).toBeInTheDocument();
};
export const noTxt = (t: string | RegExp) =>
  expect(screen.queryByText(t)).toBeNull();
export const chkLnk = (n: string | RegExp, href: string) =>
  expect(lnk(n)).toHaveAttribute("href", href);
export const waitOp = (api: unknown, op: string, req?: unknown) =>
  waitFor(() =>
    req !== undefined
      ? expect(api).toHaveBeenCalledWith(op, req)
      : expect(api).toHaveBeenCalledWith(op),
  );
const findAlert = async (txt: string | RegExp) =>
  expect(await screen.findByRole("alert")).toHaveTextContent(txt);

export const OTEL_URL_HOOK_CASES: Array<
  [string | Request | RequestInit | { url?: string }, string, string]
> = [
  ["https://x.com/p?s=1", "http.url", "https://x.com/p"],
  [{ url: "https://x.com/q?a=b#c" }, "http.target", "https://x.com/q"],
  [{}, "", ""],
];

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
  default: ({
    href,
    children,
    scroll: _s,
    ...p
  }: {
    href: string;
    children: ReactNode;
    scroll?: boolean;
  }) => createElement("a", { href, ...p }, children),
};
const OTEL_CLEAN_ATTRS = {
  "http.url": "https://x.com/p",
  "document.url": "https://x.com/d",
  "http.target": 8080,
  "ok.flag": true,
};
export const OTEL_RESOLVE_CASES = [
  [{}, null],
  [{ NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT: "   " }, null],
  [
    { NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT: "https://o/v1/traces" },
    {
      endpoint: "https://o/v1/traces",
      environment: "unknown",
      serviceVersion: "unknown",
    },
  ],
] as const;
const OTEL_SPAN_KEYS = [
  "http.url",
  "http.target",
  "url.full",
  "document.url",
] as const;
export const OTEL_REDACT_CASES = [
  [new Error("user a@b.com owes $1,234"), "Error"],
  [{}, "Error"],
  [{ name: "TypeError" }, "TypeError"],
] as const;
export const OTEL_DOC_CASES: Array<{
  defs: [object, string, PropertyDescriptor][];
  expected?: string;
}> = [
  {
    defs: [[document, "documentURI", { get: () => "https://x.com/p?t=1#h" }]],
    expected: "https://x.com/p",
  },
  {
    defs: [
      [document, "documentURI", { get: () => "" }],
      [window, "location", { get: () => ({ href: "https://x.com/h?u=1" }) }],
    ],
    expected: "https://x.com/h",
  },
  {
    defs: [
      [
        document,
        "documentURI",
        {
          get() {
            throw new Error("x");
          },
        },
      ],
      [
        window,
        "location",
        {
          get() {
            throw new Error("x");
          },
        },
      ],
    ],
  },
];
const OTEL_ERR_CASES: Array<[string, unknown, string?]> = [
  ["error", { error: new Error("s") }, "Error"],
  ["unhandledrejection", { reason: "s" }],
  ["error", { error: undefined }],
  ["unhandledrejection", { reason: new TypeError("b") }, "TypeError"],
];

export const listOfAccounts = (items: Account[]) => ({
  items,
  total: items.length,
});

export const mockAccountsStd = (
  api: ApiMockFn,
  extra: Record<string, unknown> = {},
) =>
  mockApiMap(api, {
    get_opening_balance_readiness_status_accounts_opening_balance_readiness_get:
      { needs_opening_balance: false },
    [OPS.ACC_LIST]: listOfAccounts([makeAccount({ id: "a1", name: "Cash" })]),
    [OPS.ACC_DEL]: undefined,
    ...extra,
  });
const ROUTE_RETIRED_UPLOAD = {
  "/notifications": "/upload",
  "/processing": "/upload",
  "/accounts/processing": "/upload",
  "/statements/[id]/review": "/statements/[id]",
  "/events": "/upload",
  "/review": "/upload",
};
const ROUTE_AUDIT_REDIRECTS = [
  ["/attention", "/attention", "/audit?tab=needs-you"],
  ["/confidence", "/confidence", "/audit?tab=needs-you"],
  ["/review/ai-suggestions", "/review/ai-suggestions", "/audit?tab=needs-you"],
  ["/review/run/[runId]", "/review/run/:runId", "/audit?run_id=:runId"],
] as const;
const ROUTE_QUERY_REDIRECTS = [
  ["/reconciliation/unmatched", "/reconciliation", { tab: "unmatched" }],
  ["/reconciliation/review-queue", "/reconciliation", { tab: "review-queue" }],
  ["/portfolio/prices", "/portfolio", { panel: "prices" }],
  ["/portfolio/evidence", "/portfolio", { panel: "evidence" }],
  ["/portfolio/AAPL", "/portfolio", { ticker: "AAPL" }],
  ["/accounts", "/settings", { tab: "accounts" }],
  [
    "/reconciliation/unmatched?statement_id=s1&return_to=%2Fstatements%2Fs1",
    "/reconciliation",
    { tab: "unmatched", statement_id: "s1", return_to: "/statements/s1" },
  ],
  [
    "/portfolio/evidence?source_class=property",
    "/portfolio",
    { panel: "evidence", source_class: "property" },
  ],
] as const;
const ROUTE_LEGACY_DELETED = [
  "/reconciliation/unmatched",
  "/reconciliation/review-queue",
  "/portfolio/[ticker]",
  "/portfolio/prices",
  "/portfolio/evidence",
  "/accounts",
] as const;

export const OPENING_SUGGEST_CASES = [
  ["2024-03-01", "2024-02-29"],
  ["2026-01-01", "2025-12-31"],
] as const;

export const OPENING_VALIDATION_CASES = [
  [
    "2026-03-01",
    "2026-03-01",
    "100.00",
    "Opening balances must be dated before the first report period starts.",
  ],
  ["", "2026-01-01", "", "Enter a starting balance for at least one account."],
  ["", "", "100", "Enter the as-of date for these opening balances."],
  [
    "",
    "2026-01-01",
    "1.234",
    "Balances must be positive amounts with at most two decimal places.",
  ],
] as const;

export const AI_NOTE_CASES = [
  [true, true, false, true],
  [true, false, false, false],
  [false, true, false, false],
  [true, true, true, false],
] as const;

export const API_STATUS_CASES = [
  [
    401,
    JSON.stringify({ detail: "Not authenticated" }),
    "Authentication required",
    "/login",
  ],
  [500, JSON.stringify({ detail: "Internal error" }), "Internal error", ""],
  [400, "plain text", "plain text", ""],
  [422, "false", "false", ""],
  [404, "", "Request failed with 404", ""],
] as const;
const API_DOWNLOAD_CASES = [
  ["attachment; filename*=UTF-8''report%202026.csv", "report 2026.csv"],
  ["attachment; filename*=UTF-8''%E0%A4%A", "%E0%A4%A"],
  ["attachment; filename=plain_report.csv", "plain_report.csv"],
  ["attachment; other=1", null],
  [null, null],
] as const;
const LOGIN_USER = (id: string, email: string, access_token: string) => ({
  id,
  email,
  name: null,
  created_at: "2026-01-01T00:00:00Z",
  access_token,
});

export const API_FN_CASES = [
  [
    OPS.AI_GET,
    undefined,
    "GET",
    /\/api\/users\/me\/settings$/,
    { enable_ai_reconciliation: true },
  ],
  [
    OPS.AI_PATCH,
    { body: { enable_ai_classification: true } },
    "PATCH",
    /\/api\/users\/me\/settings$/,
    { enable_ai_classification: true },
  ],
  [
    OPS.BASE_CURR,
    undefined,
    "GET",
    /\/api\/users\/me\/settings\/base-currency$/,
    { base_currency: "SGD" },
  ],
  [
    OPS.PUT_BASE_CURR,
    { body: { base_currency: "USD" } },
    "PUT",
    /\/api\/users\/me\/settings\/base-currency$/,
    { base_currency: "USD" },
  ],
] as const;
const NAV_LABEL_CASES = [
  ["/reports", "Reports"],
  ["/reports/x", "Reports"],
  ["", "Page"],
  ["/chat", "Chat"],
  ["/audit", "Audit"],
  ["/more", "More"],
  ["/settings", "Settings"],
  ["/portfolio/A", "Portfolio"],
  ["/", "Home"],
  ["/upload", "Upload"],
  ["/custom-report_page", "Custom Report Page"],
] as const;
const NAV_ACTIVE_CASES = [
  ["/", "/", true],
  ["/reports", "/", false],
  ["/reports", "/reports", true],
  ["/portfolio/p", "/portfolio", true],
  ["/reportsx", "/reports", false],
  ["/journal", "/reports", false],
] as const;
function runOtelWithNoWindow(fn: () => void) {
  const w = globalThis.window;
  // @ts-expect-error SSR simulation
  delete globalThis.window;
  try {
    fn();
  } finally {
    globalThis.window = w;
  }
}
function makeOtelEventTarget() {
  const ls: Record<string, (e: unknown) => void> = {};
  const target = {
    addEventListener: (k: string, h: (e: unknown) => void) => {
      ls[k] = h;
    },
  } as unknown as Window;
  return { ls, target };
}
function runOtelVitalsCheck(
  captureWebVitals: (
    p: ReturnType<typeof fakeOtelProvider>["provider"],
    cfg: typeof OTEL_CFG,
    fns: { onCLS?: (cb: (m: { name: string; value: number }) => void) => void },
  ) => void,
) {
  const v = fakeOtelProvider();
  let cb: ((m: { name: string; value: number }) => void) | undefined;
  captureWebVitals(v.provider, OTEL_CFG, {
    onCLS: (f) => {
      cb = f;
    },
  });
  cb?.({ name: "CLS", value: 0.1 });
  expect(v.setAttribute).toHaveBeenCalledWith("webvital.name", "CLS");
  expect(v.end).toHaveBeenCalledTimes(1);
  expect(() => captureWebVitals(v.provider, OTEL_CFG, {})).not.toThrow();
}

export async function checkChatBrief() {
  const b = await screen.findByLabelText("Advisor Brief");
  expect(
    within(b).getByText(
      "Report package is blocked by one review-required item.",
    ),
  ).toBeInTheDocument();
  expect(
    within(b).getByRole("link", { name: "Open next action" }),
  ).toHaveAttribute("href", "/reports?tab=package");
}

export function checkChatTable(container: HTMLElement) {
  hasTxts("The above analysis is for reference only.");
  expect(container.querySelector("table")).toBeInTheDocument();
  expect(container.querySelector("strong")).toBeInTheDocument();
  expect(
    (
      screen.getByPlaceholderText(
        /Ask about spending trends/i,
      ) as HTMLTextAreaElement
    ).value,
  ).toBe("Analyze this account");
}

export function mockAccountsNudgeRoutes(api: ApiMockFn) {
  let calls = 0;
  mockAccountsStd(api, {
    get_opening_balance_readiness_status_accounts_opening_balance_readiness_get:
      { needs_opening_balance: true, earliest_activity_date: "2026-01-15" },
    [OPS.ACC_LIST]: () => {
      const items = [
        makeAccount({
          id: "a1",
          name: "Cash",
          code: "1000",
          description: "Operating cash",
        }),
      ];
      if (++calls > 1)
        items.push(makeAccount({ id: "a2", name: "Savings", balance: "5000" }));
      return listOfAccounts(items);
    },
  });
}

export function checkRouteMapIntegrity(
  routes: { path: string; state: string; into?: string }[],
  pages: string[],
  targetCount: number,
) {
  const byPath = new Map(routes.map((r) => [r.path, r]));
  expect(pages.length).toBeGreaterThan(0);
  const paths = routes.map((r) => r.path);
  expect(new Set(paths).size).toBe(paths.length);
  expect(
    routes
      .filter((r) => r.state !== "redirect")
      .map((r) => r.path)
      .sort(),
  ).toEqual(pages);
  expect(routes.filter((r) => r.state === "target")).toHaveLength(targetCount);
  for (const r of routes) {
    expect(["target", "shell", "redirect"]).toContain(r.state);
    expect(
      Object.keys(r).filter((k) => !["path", "state", "into"].includes(k)),
    ).toEqual([]);
    if (r.state === "redirect") {
      expect(pages).not.toContain(r.path);
      const dest = byPath.get((r.into ?? "").split("?")[0]);
      expect(dest).toBeDefined();
      expect(dest?.state).not.toBe("redirect");
    }
  }
  return byPath;
}
const OB_INVALIDATION_KEYS = [
  ["accounts"],
  ["report", "balance-sheet"],
  ["dashboard"],
] as const;
const AI_S1 = {
  enable_ai_reconciliation: false,
  enable_ai_classification: true,
  auto_accept_ai_suggestions: true,
  auto_accept_ai_suggestions_active: true,
};
const AI_S2 = {
  enable_ai_reconciliation: false,
  enable_ai_classification: false,
  auto_accept_ai_suggestions: true,
  auto_accept_ai_suggestions_active: false,
};

export const journalSampleRes = () => ({
  items: [
    makeJournalEntry("d1", "draft", "Draft Entry", 120, "bank_statement"),
    makeJournalEntry("p1", "posted", "Posted Entry", 300),
  ],
});
const API_422_TEXT = JSON.stringify({
  detail: [{ msg: "Field required" }],
  error_id: "validation_error",
  request_id: "req-v1",
});
const NAV_EXCLUDED_TABS = [
  "/journal",
  "/reconciliation",
  "/settings?tab=accounts",
  "/statements",
  "/settings",
];
const NAV_UUID = "3f2b8c1e-9d4a-4e57-8a60-1c2d3e4f5a6b";

export const confirmDlgMock = (
  confirmLabel = "Confirm Delete",
  cancelLabel = "Cancel Delete",
  reason?: string,
  fixedLabel = false,
) => ({
  default: ({
    isOpen,
    onConfirm,
    onCancel,
    title,
    confirmLabel: cl,
  }: {
    isOpen: boolean;
    onConfirm: (r?: string) => void;
    onCancel: () => void;
    title?: string;
    confirmLabel?: string;
  }) =>
    isOpen
      ? createElement(
          "div",
          { "data-testid": "confirm-dialog" },
          title ? createElement("span", null, title) : null,
          createElement(
            "button",
            { onClick: () => onConfirm(reason) },
            fixedLabel ? confirmLabel : (cl ?? confirmLabel),
          ),
          createElement("button", { onClick: onCancel }, cancelLabel),
        )
      : null,
});

export const openingModalMock = {
  default: ({
    isOpen,
    onSuccess,
    onClose,
  }: {
    isOpen: boolean;
    onSuccess?: () => void;
    onClose?: () => void;
  }) =>
    isOpen
      ? createElement(
          "div",
          null,
          "Opening Balance Modal",
          onSuccess
            ? createElement(
                "button",
                { onClick: onSuccess },
                "Mock Record Balances",
              )
            : null,
          onClose
            ? createElement(
                "button",
                { onClick: onClose },
                "Mock Close Opening",
              )
            : null,
        )
      : null,
};

export const accountFormMock = {
  default: ({
    isOpen,
    editAccount,
    onSuccess,
    onClose,
  }: {
    isOpen: boolean;
    editAccount: Account | null;
    onSuccess?: () => void;
    onClose?: () => void;
  }) =>
    isOpen
      ? createElement(
          "div",
          null,
          editAccount ? `Edit:${editAccount.name}` : "Create Account Modal",
          onSuccess
            ? createElement("button", { onClick: onSuccess }, "Mock Save")
            : null,
          onClose
            ? createElement("button", { onClick: onClose }, "Mock Close")
            : null,
        )
      : null,
};

export function runOtelInitChecks(
  O: typeof import("@/lib/otel"),
  M: {
    url: { c: string | undefined };
    res: { c: Record<string, unknown> | undefined };
    reg: ReturnType<typeof vi.fn>;
  },
) {
  expect(O.sanitizeAttributes(OTEL_RAW_ATTRS)).toEqual(OTEL_CLEAN_ATTRS);
  expect([O.initOtel({}), O.initOtel(OTEL_ENV), O.initOtel(OTEL_ENV)]).toEqual([
    false,
    true,
    false,
  ]);
  expect(M.url.c).toBe(OTEL_CFG.endpoint);
  expect(M.reg).toHaveBeenCalledTimes(1);
  expect(M.res.c).toMatchObject({
    s: "finance-report-frontend",
    v: "abc123",
    "deployment.environment": "staging",
  });
  O.resetOtelForTests();
  runOtelWithNoWindow(() => expect(O.initOtel(OTEL_ENV)).toBe(false));
  M.reg.mockImplementationOnce(() => {
    throw new Error("boom");
  });
  expect(O.initOtel(OTEL_ENV)).toBe(false);
}

export function runOtelSpanAndErrorChecks(O: typeof import("@/lib/otel")) {
  const s = { setAttribute: vi.fn() };
  O.scrubSpanUrlAttributes(s, "https://x.com/p?s=1#f");
  for (const k of OTEL_SPAN_KEYS)
    expect(s.setAttribute).toHaveBeenCalledWith(k, "https://x.com/p");
  expect(s.setAttribute).toHaveBeenCalledWith("url.query", "");
  s.setAttribute.mockClear();
  O.scrubSpanUrlAttributes(s, undefined);
  expect(s.setAttribute).toHaveBeenCalledTimes(1);
  runOtelVitalsCheck(O.captureWebVitals);
  const f = fakeOtelProvider(),
    { ls, target } = makeOtelEventTarget();
  O.installErrorHooks(f.provider, OTEL_CFG, target);
  for (const [ev, p, n] of OTEL_ERR_CASES) {
    ls[ev](p);
    if (n)
      expect(f.recordException).toHaveBeenCalledWith({
        name: n,
        message: "[redacted]",
      });
  }
  expect(f.setAttribute).toHaveBeenCalledWith("exception.source", "onerror");
  withDefinedProps(
    [
      [
        window,
        "location",
        {
          get() {
            throw new Error("x");
          },
        },
      ],
    ],
    () => {
      O.installErrorHooks(f.provider, OTEL_CFG, target);
      expect(() => ls.error({ error: new Error("x") })).not.toThrow();
    },
  );
}

export async function runChatSessionsFlow(
  api: ApiMockFn,
  stream: ReturnType<typeof vi.fn>,
) {
  fireEvent.click(await screen.findByRole("button", { name: "Sessions" }));
  const dlg = await dlgEl("AI sessions");
  clkBtn("Close panel");
  await waitFor(() => expect(dlg).not.toBeInTheDocument());
  expect(localStorage.getItem("ai_chat_session_id")).toBe("sess-1");
  clkBtn("Sessions");
  await dlgEl("AI sessions");
  clkTxt("Cash flow review");
  await waitOp(
    api,
    OPS.CHAT_HIST,
    expect.objectContaining({
      query: expect.objectContaining({ session_id: "sess-1" }),
    }),
  );

  const ta = screen.getByPlaceholderText(/Ask about spending trends/i);
  expect(btn("Send")).toBeDisabled();
  fireEvent.change(ta, { target: { value: "Hello" } });
  fireEvent.keyDown(ta, { key: "Enter", shiftKey: false });
  await waitFor(() => expect(stream).toHaveBeenCalledTimes(1));
  fireEvent.change(ta, { target: { value: "Hello 2" } });
  clkBtn("Send");
  await waitFor(() => expect(stream).toHaveBeenCalledTimes(2));
}

export async function runAccountsDeleteFlow(
  api: ApiMockFn,
  showToast: ReturnType<typeof vi.fn>,
  probe: {
    expectNothingInvalidated: () => void;
    expectDeclaredInvalidated: () => void;
  },
) {
  await screen.findByText("Cash");
  probe.expectNothingInvalidated();
  clkBtn("Delete Account");
  clkTxt("Cancel Delete");
  await waitFor(() =>
    expect(screen.queryByTestId("confirm-dialog")).toBeNull(),
  );
  expect(api).not.toHaveBeenCalledWith(OPS.ACC_DEL, expect.anything());
  clkBtn("Delete Account");
  clkTxt("Confirm Delete");
  await waitOp(api, OPS.ACC_DEL, { path: { account_id: "a1" } });
  expect(showToast).toHaveBeenCalledWith(
    "Account deleted successfully",
    "success",
  );
  await waitFor(() => probe.expectDeclaredInvalidated());
}

export async function runAccountsNudgeFlow(
  showToast: ReturnType<typeof vi.fn>,
) {
  const nudge = await screen.findByText(/Your balance sheet may be incomplete/);
  hasTxts(/since 2026-01-15/);
  fireEvent.click(
    within(nudge.closest('[role="status"]') as HTMLElement).getByRole(
      "button",
      { name: /Set opening balances/i },
    ),
  );
  hasTxts("Opening Balance Modal");
  clkTxt("Mock Record Balances");
  expect(showToast).toHaveBeenCalledWith(
    "Opening balances recorded",
    "success",
  );
  clkTxt("Mock Close Opening");
  await waitFor(() => noTxt("Opening Balance Modal"));
  clkTxt("Cash");
  await dlgEl("Account Details");
  clkBtn("Close panel");
  await waitFor(() =>
    expect(
      screen.queryByRole("dialog", { name: "Account Details" }),
    ).toBeNull(),
  );
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
  expect(
    red
      .map(
        (r) =>
          `${r.source} -> ${r.destination} ${r.permanent ? "permanent" : "temporary"}`,
      )
      .sort(),
  ).toEqual(
    routes
      .filter((r) => r.state === "redirect")
      .map((r) => `${toNext(r.path)} -> ${toNext(r.into ?? "")} permanent`)
      .sort(),
  );
  const byS = new Map(red.map((r) => [r.source, r.destination]));
  for (const [f, t] of Object.entries(ROUTE_RETIRED_UPLOAD)) {
    expect(byPath.get(f)).toMatchObject({ state: "redirect", into: t });
    expect(byS.get(toNext(f))).toBe(toNext(t));
  }
  const dest = (s: string) => red.find((r) => r.source === s)?.destination;
  for (const [o, s, d] of ROUTE_AUDIT_REDIRECTS) {
    expect(dest(s)).toBe(d);
    expect(byPath.get(o)?.state).toBe("redirect");
    expect(pages).not.toContain(o);
  }
  for (const t of [
    "balance-sheet",
    "income-statement",
    "cash-flow",
    "package",
  ]) {
    const o = `/reports/${t}`;
    expect(dest(o)).toBe(`/reports?tab=${t}`);
    expect(byPath.get(o)?.state).toBe("redirect");
    expect(pages).not.toContain(o);
  }
  expect(red.filter((r) => r.source.startsWith("/reports/"))).toHaveLength(4);
  for (const [f, pathname, query] of ROUTE_QUERY_REDIRECTS) {
    const u = new URL(f, "http://app.test");
    let got: unknown = null;
    for (const r of red) {
      const p = getPathMatch(r.source, {
        strict: true,
        removeUnnamedParams: true,
      })(u.pathname);
      if (p) {
        const { parsedDestination: d } = prepareDestination({
          appendParamsToQuery: false,
          destination: r.destination,
          params: p,
          query: Object.fromEntries(u.searchParams),
        });
        got = { pathname: d.pathname, query: { ...d.query } };
        break;
      }
    }
    expect(got).toEqual({ pathname, query });
  }
  for (const o of ROUTE_LEGACY_DELETED) {
    expect(byPath.get(o)?.state).toBe("redirect");
    expect(pages).not.toContain(o);
  }
}

export function runLoginControlChecks() {
  const tog = screen.getByTestId("auth-mode-toggle-register"),
    cta = screen.getByTestId("login-register-cta");
  expect(tog).not.toBe(cta);
  expect(tog).toHaveAccessibleName("Register (switch to register mode)");
  expect(cta).toHaveAccessibleName("Register a new account");
  expect(screen.queryAllByRole("button", { name: /^Register$/ })).toHaveLength(
    0,
  );
  const pw = screen.getByLabelText("Password") as HTMLInputElement;
  expect(pw.type).toBe("password");
  clkBtn("Show password");
  expect(pw.type).toBe("text");
  clkBtn("Hide password");
  expect(pw.type).toBe("password");
  fireEvent.click(
    screen
      .getByText("Don't have an account?")
      .closest("p")!
      .querySelector("button")!,
  );
  fireEvent.click(
    screen
      .getByText("Already have an account?")
      .closest("p")!
      .querySelector("button")!,
  );
  hasTxts("Don't have an account?");
}

export function checkNavigationRoutes(
  N: typeof import("@/components/navigation"),
  routes: Array<{ path: string; state: string }>,
) {
  const tabs = N.bottomTabItems.map((i) => i.href),
    audit = N.auditHubItems.map((i) => i.href);
  expect(N.bottomTabItems.map((i) => [i.label, i.href])).toEqual([
    ["Home", "/"],
    ["Chat", "/chat"],
    ["Audit", "/audit"],
    ["More", "/more"],
  ]);
  expect(N.ADD_ACTION.label).toBe("Add");
  for (const h of [...NAV_EXCLUDED_TABS, ...audit])
    expect(tabs).not.toContain(h);
  expect(new Set(N.bottomTabItems.map((i) => i.icon)).size).toBe(4);
  expect(audit).toEqual(
    expect.arrayContaining(["/reconciliation", "/journal", "/upload"]),
  );
  expect(N.moreItems.map((i) => i.href)).toEqual([
    "/portfolio",
    "/reports",
    "/settings",
  ]);
  expect(N.advancedItems.map((i) => i.href)).toContain(
    "/settings?tab=accounts",
  );
  expect(
    [
      ...N.bottomTabItems,
      ...N.auditHubItems,
      ...N.moreItems,
      ...N.advancedItems,
    ]
      .filter((i) => i.label === "Portfolio")
      .map((i) => i.href),
  ).toEqual(["/portfolio"]);
  for (const [p, l] of NAV_LABEL_CASES)
    expect(N.getRouteConfig(p).label).toBe(l);
  expect(N.getRouteConfig("/unknown").Icon).toBe(N.DEFAULT_ROUTE_ICON);
  const redir = routes.filter((r) => r.state === "redirect").map((r) => r.path);
  expect(redir).toEqual(expect.arrayContaining(["/events", "/assets"]));
  for (const r of redir) expect(N.ROUTE_CONFIG[r], r).toBeUndefined();
  expect(N.getRouteConfig("/events")).toMatchObject({
    Icon: N.DEFAULT_ROUTE_ICON,
    label: "Events",
  });
  const tgts = routes
    .filter((r) => r.state === "target" && r.path.includes("["))
    .map((r) => r.path);
  expect(tgts).toContain("/statements/[id]");
  for (const t of tgts) {
    const c = t.replace(/\[[^\]]+\]/g, NAV_UUID);
    expect(N.ROUTE_CONFIG[t], t).toBeDefined();
    expect(N.getRouteConfig(c), c).toBe(N.ROUTE_CONFIG[t]);
    expect(N.getRouteConfig(c).label).not.toContain(NAV_UUID);
  }
  expect([
    N.getRouteConfig(`/statements/${NAV_UUID}`).label,
    N.getRouteConfig(`/statements/${NAV_UUID}/x`).label === "Statement",
  ]).toEqual(["Statement", false]);
  for (const [p, h, ok] of NAV_ACTIVE_CASES) expect(N.isActive(p, h)).toBe(ok);
  for (const [k, r] of Object.entries(N.APP_ROUTES))
    expect(N.ROUTE_CONFIG[r.split("?")[0]], k).toBeDefined();
  expect(N.APP_ROUTES).toMatchObject({
    HOME: "/",
    UPLOAD: "/upload",
    AUDIT: "/audit",
    CHAT: "/chat",
    RECONCILIATION_REVIEW_QUEUE: "/reconciliation?tab=review-queue",
  });
}

export async function runOpeningBalDateChecks(
  api: ApiMockFn,
  rerender: (ui: ReactElement) => void,
  renderModal: (open: boolean) => ReactElement,
) {
  expect(screen.getByLabelText("Opening balance for Cash")).toBeInTheDocument();
  expect(
    screen.getByLabelText("Opening balance for Credit Card"),
  ).toBeInTheDocument();
  expect(screen.queryByLabelText("Opening balance for Salary")).toBeNull();
  expect(screen.queryByLabelText("Opening balance for Closed")).toBeNull();
  const date = screen.getByLabelText("As-of date *");
  chgLbl("First report period starts", "2026-03-01");
  expect(date).toHaveValue("");
  clkBtn("Use 2026-02-28");
  expect(date).toHaveValue("2026-02-28");
  chgLbl("As-of date *", "2026-02-27");
  chgLbl("First report period starts", "2026-04-01");
  expect(date).toHaveValue("2026-02-27");
  rerender(renderModal(false));
  expect(screen.queryByRole("dialog")).toBeNull();
  rerender(renderModal(true));
  expect(screen.getByLabelText("As-of date *")).toHaveValue("");
  chgLbl("As-of date *", "2025-01-01");
  chgLbl("Memo", "Year-start positions");
  chgLbl("Opening balance for Cash", "42.00");
  clkBtn("Record opening balances");
  await waitOp(api, OPS.OPEN_BAL, {
    body: {
      entry_date: "2025-01-01",
      balances: { a1: "42.00" },
      memo: "Year-start positions",
    },
  });
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
  await waitOp(api, OPS.JE_VOID, {
    path: { entry_id: "p1" },
    body: { reason: "void reason" },
  });
}

export async function runApiClientStreamsCheck(
  fetchMock: ReturnType<typeof vi.fn>,
  streamFn: (op: never, req: never) => Promise<{ sessionId: string | null }>,
  uploadFn: (op: never, req: never) => Promise<unknown>,
  downloadFn: (op: never, req: never) => Promise<{ filename: string | null }>,
) {
  fetchMock.mockResolvedValueOnce({
    ok: true,
    status: 200,
    headers: {
      get: (h: string) => (h.toLowerCase() === "x-session-id" ? "s1" : null),
    },
    text: async () => "",
  });
  expect(
    (
      await streamFn(
        OPS.CHAT_POST as never,
        { body: { message: "hi" } } as never,
      )
    ).sessionId,
  ).toBe("s1");
  const fd = new FormData();
  fetchMock.mockResolvedValueOnce({ ok: true, status: 204 });
  expect(
    await uploadFn(OPS.UPL as never, { body: fd } as never),
  ).toBeUndefined();
  fetchMock.mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: async () => ({ id: "s1" }),
  });
  expect(await uploadFn(OPS.UPL as never, { body: fd } as never)).toEqual({
    id: "s1",
  });
  const csv = new Blob(["data"], { type: "text/csv" });
  for (const [hdr, expected] of API_DOWNLOAD_CASES) {
    global.fetch = makeFetchMock(
      200,
      csv,
      hdr ? { "content-disposition": hdr } : {},
    );
    expect(
      (await downloadFn(OPS.EXP as never, { query: {} } as never)).filename,
    ).toBe(expected);
  }
  global.fetch = fetchMock as unknown as typeof fetch;
}
function checkCoveragePeriodNote(expectedText: string, btnDisabled = true) {
  expect(screen.getByTestId("report-period-range")).toHaveTextContent(
    expectedText,
  );
  if (btnDisabled) expect(btn("Previous period")).toBeDisabled();
  else expect(btn("Previous period")).toBeEnabled();
}

export async function runChatErrorStates(
  renderChat: () => { unmount: () => void },
  stream: ReturnType<typeof vi.fn>,
) {
  stream
    .mockResolvedValueOnce({
      response: { body: null } as never,
      sessionId: "s3",
    })
    .mockRejectedValueOnce(new Error("Network Fail"));
  const v1 = renderChat();
  await waitFor(() => noTxt(/Loading chat history/i));
  const ta = screen.getByPlaceholderText(/Ask about spending trends/i);
  fireEvent.change(ta, { target: { value: "a" } });
  clkBtn("Send");
  await screen.findByText("No response stream available.");
  fireEvent.change(ta, { target: { value: "b" } });
  clkBtn("Send");
  await waitFor(() =>
    expect(screen.getAllByText("Network Fail").length).toBeGreaterThan(0),
  );
  v1.unmount();
}

export async function runAiSettingsSaveFlow(
  api: ApiMockFn,
  showToast: ReturnType<typeof vi.fn>,
) {
  await screen.findByText("AI Settings");
  chkLnk(/Review AI suggestions/i, "/audit?tab=needs-you#ai-suggestions");
  expect(screen.getByLabelText("Auto-accept AI suggestions")).toBeDisabled();
  expect(btn(/Save changes/i)).toBeDisabled();
  clkLbl("Enable AI classification");
  expect(screen.queryByRole("note")).toBeNull();
  clkBtn(/Reset/i);
  expect(screen.getByLabelText("Enable AI classification")).not.toBeChecked();
  clkLbl("Enable AI classification");
  clkBtn(/Save changes/i);
  await waitOp(api, OPS.AI_PATCH, { body: { enable_ai_classification: true } });
  await waitFor(() =>
    expect(showToast).toHaveBeenCalledWith("AI settings saved", "success"),
  );
}

export function checkChangedChoicesFn(
  changedChoices: (
    s: typeof AI_S1 | null,
    d: typeof AI_S1,
  ) => Record<string, unknown>,
) {
  expect(
    changedChoices(AI_S1, { ...AI_S1, auto_accept_ai_suggestions: false }),
  ).toEqual({ auto_accept_ai_suggestions: false });
  expect(
    changedChoices(AI_S1, {
      ...AI_S1,
      auto_accept_ai_suggestions_active: false,
    }),
  ).toEqual({});
  expect(changedChoices(null, AI_S1)).toEqual({
    enable_ai_reconciliation: false,
    enable_ai_classification: true,
    auto_accept_ai_suggestions: true,
  });
}

export async function runJournalEmptyAndDetails(
  api: ApiMockFn,
  renderPage: () => { unmount: () => void },
) {
  api
    .mockRejectedValueOnce(new Error("journal failed"))
    .mockResolvedValue({ items: [] });
  const v0 = renderPage();
  await screen.findByText("Failed to load entries");
  clkBtn("Retry loading journal entries");
  await screen.findByText("No journal entries yet");
  clkBtn("New Entry");
  clkBtn("Mock Submit");
  await waitFor(() => expect(api).toHaveBeenCalledTimes(3));
  fireEvent.click(
    await screen.findByRole("button", { name: "Create First Entry" }),
  );
  hasTxts("Mock Submit");
  v0.unmount();

  const res = journalSampleRes();
  api.mockResolvedValueOnce(res).mockResolvedValueOnce({ items: [] });
  const v1 = renderPage();
  await screen.findByText("Draft Entry");
  hasTxts(/120\.00/);
  clkTxt("Draft Entry");
  expect(await dlgEl("Journal Entry Details")).toHaveTextContent(
    "bank statement",
  );
  clkBtn("Close modal");
  await waitFor(() =>
    expect(
      screen.queryByRole("dialog", { name: "Journal Entry Details" }),
    ).toBeNull(),
  );
  clkBtn("draft");
  await waitOp(api, OPS.JE_LIST, { query: { status_filter: "draft" } });
  v1.unmount();
}

export async function runApi422AndGuards(
  fetchMock: ReturnType<typeof vi.fn>,
  apiOperation: typeof import("@/lib/api").apiOperation,
  ApiErrorCtor: new (...a: never[]) => Error,
  mockLoc: { href: string; pathname: string },
) {
  fetchMock.mockResolvedValueOnce({
    ok: false,
    status: 422,
    text: async () => API_422_TEXT,
  });
  const err = await apiOperation(OPS.ACC_ADD, {
    body: { name: "", type: "ASSET" as never, currency: "SGD" },
  }).catch((e) => e);
  expect(err).toBeInstanceOf(ApiErrorCtor);
  expect(err).toMatchObject({
    status: 422,
    errorId: "validation_error",
    requestId: "req-v1",
  });
  expect((err as Error).message).toContain("Field required");

  const oldW = (globalThis as { window?: unknown }).window;
  vi.stubGlobal("window", undefined);
  fetchMock.mockResolvedValueOnce({
    ok: false,
    status: 401,
    text: async () => "no",
  });
  await expect(apiOperation(OPS.BASE_CURR)).rejects.toThrow(
    "Authentication required",
  );
  vi.stubGlobal("window", oldW);

  Object.defineProperty(window, "location", {
    configurable: true,
    get: () => ({
      pathname: "/dashboard",
      set href(_: string) {
        throw new Error("navigation blocked");
      },
    }),
  });
  fetchMock.mockResolvedValueOnce({
    ok: false,
    status: 401,
    text: async () => "unauthorized",
  });
  await expect(apiOperation(OPS.BASE_CURR)).rejects.toThrow(
    "Authentication required - redirect failed",
  );
  Object.defineProperty(window, "location", {
    value: mockLoc,
    writable: true,
    configurable: true,
  });
}

export async function runLoginErrorAndSpinner(
  api: ApiMockFn,
  setUserMock: ReturnType<typeof vi.fn>,
  pushMock: ReturnType<typeof vi.fn>,
  submit: (e: string, p: string, b: string) => void,
  renderLogin: () => { unmount: () => void },
) {
  api.mockRejectedValueOnce(new Error("invalid credentials"));
  const first = renderLogin();
  submit("bad@e.com", "password123", "Sign In");
  const a = await alertEl();
  expect(a).toHaveAttribute("aria-live", "assertive");
  expect(a).toHaveTextContent("invalid credentials");
  expect(setUserMock).not.toHaveBeenCalled();
  expect(pushMock).not.toHaveBeenCalled();
  first.unmount();

  let resolve!: (v: unknown) => void;
  api.mockReturnValueOnce(
    new Promise((r) => {
      resolve = r;
    }),
  );
  renderLogin();
  submit("a@b.com", "12345678", "Sign In");
  await screen.findByText("Processing...");
  resolve(LOGIN_USER("u1", "a@b.com", "tok"));
  await waitFor(() =>
    expect(screen.queryByText("Processing...")).not.toBeInTheDocument(),
  );
}

export async function runApiFnWrappersCheck(
  callStream: (op: never, req: never) => Promise<{ sessionId: string | null }>,
  callUpload: (op: never, req: never) => Promise<unknown>,
  callDownload: (op: never, req: never) => Promise<unknown>,
) {
  vi.stubGlobal("fetch", makeFetchMock(200, "", { "X-Session-Id": "sess-1" }));
  expect(
    (
      await callStream(
        OPS.CHAT_POST as never,
        { body: { message: "hi" } } as never,
      )
    ).sessionId,
  ).toBe("sess-1");
  const fd = new FormData();
  fd.append("file", new Blob(["data"]), "test.pdf");
  vi.stubGlobal("fetch", makeFetchMock(200, { uploaded: true }));
  expect(await callUpload(OPS.UPL as never, { body: fd } as never)).toEqual({
    uploaded: true,
  });
  const csv = new Blob(["ok"], { type: "text/csv" });
  vi.stubGlobal(
    "fetch",
    makeFetchMock(200, csv, {
      "content-disposition": 'attachment; filename="cash-flow.csv"',
    }),
  );
  expect(
    await callDownload(OPS.EXP as never, { query: {} } as never),
  ).toMatchObject({ blob: csv, filename: "cash-flow.csv" });
}

export async function runAiToggleAndErrorFlows(
  api: ApiMockFn,
  renderPanel: () => { unmount: () => void },
) {
  mockAiSettingsRoutes(api, AI_S1, {
    ...AI_S1,
    auto_accept_ai_suggestions: false,
    auto_accept_ai_suggestions_active: false,
  });
  const v1 = renderPanel();
  await waitFor(() =>
    expect(screen.getByLabelText("Auto-accept AI suggestions")).toBeChecked(),
  );
  clkLbl("Auto-accept AI suggestions");
  clkBtn(/Save changes/i);
  await waitOp(api, OPS.AI_PATCH, {
    body: { auto_accept_ai_suggestions: false },
  });
  v1.unmount();
  mockAiSettingsRoutes(api, AI_S2, {
    ...AI_S2,
    enable_ai_reconciliation: true,
  });
  const v2 = renderPanel();
  await screen.findByText("AI Settings");
  clkLbl("Enable AI reconciliation");
  clkBtn(/Save changes/i);
  await waitOp(api, OPS.AI_PATCH, { body: { enable_ai_reconciliation: true } });
  v2.unmount();

  mockAiSettingsRoutes(api, AI_SETTINGS_DEFAULT, () => {
    throw new Error("Save failed");
  });
  const v3 = renderPanel();
  await screen.findByText("AI Settings");
  clkLbl("Enable AI classification");
  clkBtn(/Save changes/i);
  await findAlert("Save failed");
  expect(screen.getByLabelText("Enable AI classification")).toBeChecked();
  v3.unmount();
  api.mockRejectedValue(new Error("Load failed"));
  const v4 = renderPanel();
  await findAlert("Load failed");
  v4.unmount();
}

export async function runOpeningBalInvalidateAndErrors(
  api: ApiMockFn,
  coverageKey: readonly unknown[],
  renderModal: (
    props: { accounts: Account[]; onClose: () => void; onSuccess: () => void },
    wrapper?: ReturnType<typeof clientWrapper>,
  ) => { unmount: () => void },
) {
  api.mockResolvedValueOnce({ id: "opening-entry" });
  const c = new QueryClient(),
    keys = [[...coverageKey, "2026-10-22"], ...OB_INVALIDATION_KEYS];
  for (const k of keys) c.setQueryData(k, { seeded: true });
  const onSuccess = vi.fn();
  const v0 = renderModal(
    { accounts: OPENING_ACCOUNTS, onClose: vi.fn(), onSuccess },
    clientWrapper(c),
  );
  chgLbl("As-of date *", "2026-06-30");
  chgLbl("Opening balance for Cash", "100.00");
  clkBtn("Record opening balances");
  await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
  expect(keys.map((k) => c.getQueryState(k)?.isInvalidated)).toEqual([
    true,
    true,
    true,
    true,
  ]);
  v0.unmount();

  const v1 = renderModal({
    accounts: [],
    onClose: vi.fn(),
    onSuccess: vi.fn(),
  });
  hasTxts(
    "Create an asset, liability, or equity account first, then set its opening balance.",
  );
  expect(btn("Record opening balances")).toBeDisabled();
  v1.unmount();

  api.mockRejectedValueOnce(new Error("Account has activity before this date"));
  const onClose = vi.fn();
  renderModal({ accounts: OPENING_ACCOUNTS, onClose, onSuccess: vi.fn() });
  chgLbl("As-of date *", "2026-01-01");
  chgLbl("Opening balance for Cash", "100");
  clkBtn("Record opening balances");
  await screen.findByText("Account has activity before this date");
  expect(onClose).not.toHaveBeenCalled();
}

export async function runHomeCoverageBounds(
  api: ApiMockFn,
  renderHome: () => { unmount: () => void },
  setUrl: (u: string) => void,
) {
  const bsDates = () =>
    opCalls(api, OPS.BS)
      .map(
        ([, r]) =>
          ((r ?? {}) as { query?: Record<string, unknown> }).query?.as_of_date,
      )
      .sort();
  const v1 = renderHome(),
    bal = await screen.findByTestId("cockpit-card-balance-sheet");
  await waitFor(() =>
    expect(
      within(bal).getByText("Change in period").nextElementSibling,
    ).toHaveTextContent("+SGD 1,500"),
  );
  expect(within(bal).getByTestId("change-in-period-basis")).toHaveTextContent(
    "Jul 1, 2026, when your cash opening balances are complete.",
  );
  checkCoveragePeriodNote("Jul 1, 2026 – Oct 22, 2026", true);
  chkLnk("Add an opening balance", "/settings?tab=accounts");
  expect(bsDates()).toEqual(["2026-07-01", "2026-10-22"]);
  v1.unmount();
  api.mockClear();
  setUrl("/?period=All&end=2026-10-22");
  renderHome();
  await waitFor(() =>
    checkCoveragePeriodNote("Jul 1, 2026 – Oct 22, 2026", true),
  );
}

export async function runHomeCoverageJump(
  renderHome: () => { unmount: () => void },
  setBounds: (s: string | null, l: string | null) => void,
  setUrl: (u: string) => void,
  testUrlFn: () => string,
) {
  setBounds(null, null);
  const v1 = renderHome();
  await waitFor(() =>
    checkCoveragePeriodNote("Nov 1, 2025 – Oct 22, 2026", false),
  );
  expect(screen.queryByTestId("report-coverage-note")).toBeNull();
  v1.unmount();
  setBounds("2025-01-01", "2025-03-31");
  setUrl("/?end=2026-10-22");
  renderHome();
  const b = await screen.findByTestId("report-latest-statement-banner");
  expect(b).toHaveTextContent(
    "Latest statement ends Mar 31, 2025, before this period.",
  );
  fireEvent.click(
    within(b).getByRole("button", { name: /Jump to Mar 31, 2025/i }),
  );
  expect(testUrlFn()).toBe("/?end=2025-03-31");
}

export async function runLoginSubmitFlows(
  api: ApiMockFn,
  setUserMock: ReturnType<typeof vi.fn>,
  pushMock: ReturnType<typeof vi.fn>,
  trackFn: unknown,
  signupEv: unknown,
  renderLogin: () => { unmount: () => void },
) {
  const sub = (e: string, p: string, b: string) => {
    chgLbl("Email Address", e);
    chgLbl("Password", p);
    clkBtn(b);
  };
  api.mockResolvedValueOnce(LOGIN_USER("u1", "u@e.com", "t1"));
  const v1 = renderLogin();
  sub("u@e.com", "password123", "Sign In");
  await waitOp(api, OPS.LOGIN, {
    body: { email: "u@e.com", password: "password123" },
  });
  expect(setUserMock).toHaveBeenCalledWith("u1", "u@e.com");
  expect(pushMock).toHaveBeenCalledWith("/");
  expect(vi.mocked(trackFn as never)).not.toHaveBeenCalledWith(signupEv);
  v1.unmount();

  api.mockResolvedValueOnce(LOGIN_USER("u2", "n@e.com", "t2"));
  renderLogin();
  fireEvent.click(screen.getByTestId("auth-mode-toggle-register"));
  sub("n@e.com", "password123", "Create Account");
  await waitOp(api, OPS.REG, {
    body: { email: "n@e.com", password: "password123" },
  });
  await waitFor(() =>
    expect(vi.mocked(trackFn as never)).toHaveBeenCalledWith(signupEv),
  );
}

export const OTEL_SCRUB_CASES = [
  [
    "https://app.example.com/reports?email=a@b.com#frag",
    "https://app.example.com/reports",
  ],
  ["https://app.example.com/reports", "https://app.example.com/reports"],
  ["/accounts/42?token=secret", "/accounts/42"],
  ["/accounts/42#balance", "/accounts/42"],
  ["/accounts/42", "/accounts/42"],
  ["", ""],
] as const;
const OTEL_RAW_ATTRS = {
  "user.email": "a@b.com",
  "txn.amount": 100,
  "bank.account_number": "123",
  Authorization: "Bearer x",
  "session.cookie": "c",
  "http.url": "https://x.com/p?q=1#h",
  "document.url": "https://x.com/d?a=b",
  "http.target": 8080,
  missing: undefined,
  empty: null,
  "ok.flag": true,
};
const OTEL_ENV = {
  NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT: OTEL_CFG.endpoint,
  NEXT_PUBLIC_DEPLOYMENT_ENVIRONMENT: "staging",
  NEXT_PUBLIC_GIT_SHA: "abc123",
};

export const CHAT_GROUNDED_HEADERS = {
  "X-Advisor-Metadata": JSON.stringify({
    citations: [
      {
        label: "Balance Sheet",
        source_ref: "balance_sheet.total_equity",
        confidence_tier: "TRUSTED",
        href: "/reports/balance-sheet",
      },
    ],
    actions: [
      {
        kind: "reconciliation_review",
        label: "Review 2",
        href: "/reconciliation?tab=review-queue",
        count: 2,
      },
    ],
  }),
};

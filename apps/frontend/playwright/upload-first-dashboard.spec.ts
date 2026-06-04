import { expect, test, type Page } from "@playwright/test";

const COLD_ROUTE_TIMEOUT_MS = 10_000;

const workflowStatus = {
  primary_state: "needs_action",
  next_action: { type: "review_required", count: 1, href: "/review" },
  report_readiness: { state: "blocked", blocking_count: 1, href: "/reports" },
  event_counts: { unread: 2, action_required: 1, blocked: 0 },
  active_session: {
    id: "upload-home-session",
    status: "active",
    title: "Upload-to-report session",
    summary: "Current upload, processing, review, and report-readiness work.",
    started_at: "2026-06-03T07:00:00Z",
    last_event_at: "2026-06-03T08:00:00Z",
    source_count: 2,
    primary_state: "needs_action",
    report_readiness: { state: "blocked", blocking_count: 1, href: "/reports" },
    event_counts: { unread: 2, action_required: 1, blocked: 0 },
  },
};

const workflowEvents = {
  total: 2,
  items: [
    {
      id: "upload-home-review",
      user_id: "upload-home-user",
      session_id: "upload-home-session",
      occurred_at: "2026-06-03T08:00:00Z",
      family: "review.required",
      severity: "action_required",
      status: "unread",
      title: "Review required",
      summary: "Confirm one low-confidence extraction before reports are ready.",
      source_type: "bank_statement",
      source_id: "statement-review",
      action_href: "/review",
      report_impact: "blocked",
      dedupe_key: "upload-home:review",
      created_at: "2026-06-03T08:00:00Z",
      updated_at: "2026-06-03T08:00:00Z",
    },
    {
      id: "upload-home-posted",
      user_id: "upload-home-user",
      session_id: "upload-home-session",
      occurred_at: "2026-06-03T07:00:00Z",
      family: "ledger.auto_posted",
      severity: "success",
      status: "read",
      title: "Safe entries posted",
      summary: "Automation posted high-confidence entries.",
      source_type: "journal",
      source_id: "journal-posted",
      action_href: "/journal",
      report_impact: "ready",
      dedupe_key: "upload-home:posted",
      created_at: "2026-06-03T07:00:00Z",
      updated_at: "2026-06-03T07:00:00Z",
    },
  ],
  sessions: [workflowStatus.active_session],
};

async function installDashboardMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("finance_access_token", "upload-home-token");
    localStorage.setItem("finance_user_id", "upload-home-user");
    localStorage.setItem("finance_user_email", "upload-home@example.com");
  });

  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};

    if (path === "/api/workflow/status") {
      body = workflowStatus;
    } else if (path === "/api/workflow/events") {
      body = workflowEvents;
    } else if (path === "/api/accounts" || path === "/api/statements" || path.startsWith("/api/journal-entries")) {
      body = { items: [], total: 0 };
    } else if (path === "/api/accounts/processing/summary") {
      body = { pending_count: 0, pending_total: "0.00", current_balance: "0.00", currency: "SGD", oldest_pending_date: null };
    } else if (path.startsWith("/api/reports/balance-sheet")) {
      body = {
        as_of_date: "2026-06-03",
        currency: "SGD",
        assets: [{ account_id: "cash", name: "Cash", type: "ASSET", amount: "1000.00" }],
        liabilities: [],
        equity: [],
        total_assets: "1000.00",
        total_liabilities: "0.00",
        total_equity: "1000.00",
        equation_delta: "0.00",
        is_balanced: true,
      };
    } else if (path.startsWith("/api/reports/income-statement")) {
      body = { start_date: "2026-01-01", end_date: "2026-06-03", currency: "SGD", income: [], expenses: [], total_income: "0.00", total_expenses: "0.00", net_income: "0.00", trends: [] };
    } else if (path.startsWith("/api/reports/trend")) {
      body = { points: [] };
    } else if (path === "/api/income/annualized") {
      body = { annualized_salary: "0.00", annualized_bonus: "0.00", annualized_dividend: "0.00", annualized_total: "0.00", currency: "SGD", as_of: "2026-06-03" };
    } else if (path === "/api/assets/restricted") {
      body = [];
    } else if (path === "/api/reconciliation/stats") {
      body = { total_transactions: 0, matched_transactions: 0, unmatched_transactions: 0, pending_review: 0, auto_accepted: 0, match_rate: 0, score_distribution: {} };
    } else if (path === "/api/reconciliation/unmatched") {
      body = { items: [], total: 0 };
    }

    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

async function expectNoDocumentHorizontalScroll(page: Page) {
  const metrics = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    scrollX: window.scrollX,
  }));

  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth);
  expect(metrics.scrollX).toBe(0);
}

test.describe("AC19.4.7 upload-first dashboard smoke", () => {
  for (const scenario of [
    { name: "desktop", viewport: { width: 1440, height: 1000 } },
    { name: "mobile", viewport: { width: 390, height: 844 } },
  ]) {
    test(`${scenario.name} renders upload-to-report home before secondary analytics`, async ({ page }) => {
      await page.setViewportSize(scenario.viewport);
      await installDashboardMocks(page);

      await page.goto("/dashboard", { waitUntil: "networkidle" });

      const uploadHome = page.getByLabel("Upload-to-report home");
      await expect(uploadHome.getByRole("heading", { name: "Upload-to-report session" })).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
      await expect(uploadHome.getByRole("link", { name: "Review required", exact: true })).toHaveAttribute("href", "/review");
      await expect(uploadHome.getByRole("link", { name: "Report readiness" })).toHaveAttribute("href", "/reports");
      await expect(uploadHome.getByRole("heading", { name: "Recent session timeline" })).toBeVisible();
      await expect(uploadHome.getByRole("heading", { name: "Routine automation" })).toBeVisible();

      const homeBox = await uploadHome.boundingBox();
      const analyticsBox = await page.getByLabel("Dashboard analytics").boundingBox();
      expect(homeBox).not.toBeNull();
      expect(analyticsBox).not.toBeNull();
      expect(homeBox!.y).toBeLessThan(analyticsBox!.y);
      await expectNoDocumentHorizontalScroll(page);
    });
  }
});

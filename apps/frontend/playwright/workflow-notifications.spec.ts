import { expect, test, type Page } from "@playwright/test";

const COLD_ROUTE_TIMEOUT_MS = 10_000;

const workflowStatus = {
  primary_state: "needs_action",
  next_action: { type: "review_required", count: 1, href: "/review" },
  report_readiness: { state: "blocked", blocking_count: 1, href: "/reports" },
  event_counts: { unread: 2, action_required: 1, blocked: 1 },
  active_session: {
    id: "workflow-session",
    status: "active",
    title: "Upload-to-report session",
    summary: "Current upload, processing, review, and report-readiness work.",
    started_at: "2026-06-03T06:00:00Z",
    last_event_at: "2026-06-03T08:00:00Z",
    source_count: 3,
    primary_state: "needs_action",
    report_readiness: { state: "blocked", blocking_count: 1, href: "/reports" },
    event_counts: { unread: 2, action_required: 1, blocked: 1 },
  },
};

const workflowEvents = {
  total: 3,
  items: [
    {
      id: "workflow-blocked",
      user_id: "workflow-user",
      session_id: "workflow-session",
      occurred_at: "2026-06-03T08:00:00Z",
      family: "reconciliation.blocked",
      severity: "blocked",
      status: "unread",
      title: "Reconciliation blocked",
      summary: "Match two transactions before reports can be trusted.",
      source_type: "reconciliation",
      source_id: "source-blocked",
      action_href: "/reconciliation/unmatched",
      report_impact: "blocked",
      dedupe_key: "workflow:blocker",
      created_at: "2026-06-03T08:00:00Z",
      updated_at: "2026-06-03T08:00:00Z",
    },
    {
      id: "workflow-review",
      user_id: "workflow-user",
      session_id: "workflow-session",
      occurred_at: "2026-06-03T07:00:00Z",
      family: "review.required",
      severity: "action_required",
      status: "unread",
      title: "Review required",
      summary: "Confirm one low-confidence statement extraction.",
      source_type: "bank_statement",
      source_id: "source-review",
      action_href: "/review",
      report_impact: "blocked",
      dedupe_key: "workflow:review",
      created_at: "2026-06-03T07:00:00Z",
      updated_at: "2026-06-03T07:00:00Z",
    },
    {
      id: "workflow-success",
      user_id: "workflow-user",
      session_id: "workflow-session",
      occurred_at: "2026-06-03T06:00:00Z",
      family: "ledger.auto_posted",
      severity: "success",
      status: "read",
      title: "Safe entries posted",
      summary: "Automation posted high-confidence entries.",
      source_type: "journal",
      source_id: "source-success",
      action_href: "/journal",
      report_impact: "ready",
      dedupe_key: "workflow:success",
      created_at: "2026-06-03T06:00:00Z",
      updated_at: "2026-06-03T06:00:00Z",
    },
  ],
  sessions: [workflowStatus.active_session],
};

async function installWorkflowMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("finance_user_id", "workflow-user");
    localStorage.setItem("finance_user_email", "workflow@example.com");
  });

  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};

    if (path === "/api/workflow/status") {
      body = workflowStatus;
    } else if (path === "/api/workflow/events") {
      body = workflowEvents;
    } else if (path.startsWith("/api/workflow/events/")) {
      body = workflowEvents.items[0];
    } else if (path === "/api/accounts") {
      body = { items: [{ id: "cash", name: "Cash", type: "ASSET", currency: "SGD", is_active: true }], total: 1 };
    } else if (path === "/api/accounts/processing/summary") {
      body = { pending_count: 0, pending_total: "0.00", current_balance: "0.00", currency: "SGD", oldest_pending_date: null };
    } else if (path === "/api/statements") {
      body = { items: [{ id: "statement", status: "approved" }], total: 1 };
    } else if (path === "/api/statements/pending-review") {
      body = { items: [{ id: "statement" }], total: 1 };
    } else if (path === "/api/statements/stage2/queue") {
      body = { pending_matches: [], consistency_checks: [], has_unresolved_checks: false };
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
    } else if (path.startsWith("/api/journal-entries")) {
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

test.describe("AC19.3.7 workflow notification smoke", () => {
  for (const scenario of [
    { name: "desktop", viewport: { width: 1440, height: 1000 }, isMobile: false },
    { name: "mobile", viewport: { width: 390, height: 844 }, isMobile: true },
  ]) {
    test(`${scenario.name} shows workflow badge, inbox, and dashboard status feed`, async ({ page }) => {
      await page.setViewportSize(scenario.viewport);
      await installWorkflowMocks(page);

      await page.goto("/dashboard", { waitUntil: "networkidle" });
      await expect(page.getByRole("heading", { name: "Workflow status" })).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
      await expect(page.getByRole("link", { name: "Review required", exact: true })).toHaveAttribute("href", "/review");

      await page.getByRole("button", { name: /Workflow events/i }).click();
      const dialog = page.getByRole("dialog", { name: "Workflow events" });
      await expect(dialog).toBeVisible();
      await expect(dialog.getByRole("heading", { name: "Upload-to-report session", exact: true })).toBeVisible();
      await expect(dialog.getByRole("list", { name: "Upload-to-report session timeline" })).toBeVisible();
      await expect(dialog.getByRole("link", { name: "Open" }).first()).toHaveAttribute(
        "href",
        "/reconciliation/unmatched",
      );

      await expectNoDocumentHorizontalScroll(page);
    });
  }
});

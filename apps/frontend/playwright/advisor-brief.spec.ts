import { expect, test, type Page } from "@playwright/test";

const COLD_ROUTE_TIMEOUT_MS = 10_000;

const workflowStatus = {
  primary_state: "needs_action",
  next_action: { type: "review_required", count: 1, href: "/review", label: "Review required" },
  report_readiness: { state: "blocked", blocking_count: 1, href: "/reports/package" },
  event_counts: { unread: 1, action_required: 1, blocked: 0 },
};

const workflowEvents = {
  total: 1,
  items: [
    {
      id: "advisor-brief-review",
      user_id: "advisor-user",
      session_id: "advisor-session",
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
      dedupe_key: "advisor-brief:review",
      created_at: "2026-06-03T08:00:00Z",
      updated_at: "2026-06-03T08:00:00Z",
    },
  ],
  sessions: [
    {
      id: "advisor-session",
      status: "active",
      title: "Advisor Brief session",
      summary: "Current upload, processing, review, and report-readiness work.",
      started_at: "2026-06-03T07:00:00Z",
      last_event_at: "2026-06-03T08:00:00Z",
      source_count: 2,
      primary_state: "needs_action",
      report_readiness: { state: "blocked", blocking_count: 1, href: "/reports/package" },
      event_counts: { unread: 1, action_required: 1, blocked: 0 },
    },
  ],
};

const chatSuggestions = {
  suggestions: ["How is my Advisor Brief?"],
  structured_suggestions: [
    {
      basis: "Report package is blocked by one review-required item.",
      confidence_tier: "blocked",
      source_refs: ["workflow.status", "report_package.readiness"],
      limitation: "Review the blocker before relying on this report.",
      next_action_href: "/reports/package",
    },
    {
      basis: "Market prices are stale for one portfolio holding.",
      confidence_tier: "stale",
      source_refs: ["market_data.freshness"],
      limitation: "Portfolio value may be outdated until prices refresh.",
      next_action_href: "/portfolio/prices/update",
    },
  ],
};

async function installAdvisorBriefMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("finance_access_token", "advisor-brief-token");
    localStorage.setItem("finance_user_id", "advisor-user");
    localStorage.setItem("finance_user_email", "advisor@example.com");
  });

  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};

    if (path === "/api/chat/suggestions") {
      body = chatSuggestions;
    } else if (path === "/api/workflow/status") {
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
      body = {
        start_date: "2026-01-01",
        end_date: "2026-06-03",
        currency: "SGD",
        income: [],
        expenses: [],
        total_income: "0.00",
        total_expenses: "0.00",
        net_income: "0.00",
        trends: [],
      };
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

test.describe("AC21.3.4 Advisor Brief responsive layout", () => {
  for (const scenario of [
    { name: "desktop", viewport: { width: 1440, height: 1000 } },
    { name: "mobile", viewport: { width: 390, height: 844 } },
  ]) {
    test(`${scenario.name} advisor-brief desktop and mobile layouts avoid horizontal overflow`, async ({ page }) => {
      await page.setViewportSize(scenario.viewport);
      await installAdvisorBriefMocks(page);

      await page.goto("/dashboard", { waitUntil: "networkidle" });

      const brief = page.getByLabel("Advisor Brief");
      await expect(brief.getByRole("heading", { name: "Advisor Brief" })).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
      await expect(brief.getByText("Readiness blocker")).toBeVisible();
      await expect(brief.getByText("Refresh market data")).toBeVisible();
      await expect(brief.getByRole("link", { name: "Open next action" }).nth(0)).toHaveAttribute("href", "/reports/package");
      await expect(brief.getByRole("link", { name: "Open next action" }).nth(1)).toHaveAttribute("href", "/portfolio/prices");
      await expect(brief.getByRole("link", { name: "Ask about this" }).nth(0)).toHaveAttribute("href", /\/chat\?prompt=/);
      await expectNoDocumentHorizontalScroll(page);
    });
  }
});

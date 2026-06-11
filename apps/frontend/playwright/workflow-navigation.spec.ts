import { expect, test, type Page } from "@playwright/test";

const COLD_ROUTE_TIMEOUT_MS = 10_000;

const workflowStatus = {
  primary_state: "needs_action",
  next_action: { type: "review_required", count: 2, href: "/review" },
  report_readiness: { state: "blocked", blocking_count: 1, href: "/reports" },
  event_counts: { unread: 4, action_required: 2, blocked: 1 },
  active_session: {
    id: "workflow-session",
    status: "active",
    title: "Upload-to-report session",
    summary: "Current upload, processing, review, and report-readiness work.",
    started_at: "2026-06-04T01:00:00Z",
    last_event_at: "2026-06-04T02:00:00Z",
    source_count: 4,
    primary_state: "needs_action",
    report_readiness: { state: "blocked", blocking_count: 1, href: "/reports" },
    event_counts: { unread: 4, action_required: 2, blocked: 1 },
  },
};

async function installNavigationMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("finance_user_id", "workflow-navigation-user");
    localStorage.setItem("finance_user_email", "workflow-navigation@example.com");
  });

  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};

    if (path === "/api/workflow/status") {
      body = workflowStatus;
    } else if (path === "/api/workflow/events") {
      body = { items: [], total: 0, sessions: [] };
    } else if (path.startsWith("/api/reports/balance-sheet")) {
      body = {
        as_of_date: "2026-06-04",
        currency: "SGD",
        assets: [],
        liabilities: [],
        equity: [],
        total_assets: "0.00",
        total_liabilities: "0.00",
        total_equity: "0.00",
        equation_delta: "0.00",
        is_balanced: true,
      };
    } else if (path.startsWith("/api/reports/income-statement")) {
      body = {
        start_date: "2026-01-01",
        end_date: "2026-06-04",
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
      body = {
        annualized_salary: "0.00",
        annualized_bonus: "0.00",
        annualized_dividend: "0.00",
        annualized_total: "0.00",
        currency: "SGD",
        as_of: "2026-06-04",
      };
    } else if (path === "/api/assets/restricted") {
      body = [];
    } else if (path === "/api/reconciliation/stats") {
      body = {
        total_transactions: 0,
        matched_transactions: 0,
        unmatched_transactions: 0,
        pending_review: 0,
        auto_accepted: 0,
        match_rate: 0,
        score_distribution: {},
      };
    } else if (path === "/api/reconciliation/unmatched") {
      body = { items: [], total: 0 };
    } else if (path === "/api/accounts") {
      body = { items: [], total: 0 };
    } else if (path === "/api/statements") {
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

test.describe("AC19.6.7 workflow navigation folding", () => {
  test.beforeEach(async ({ page }) => {
    await installNavigationMocks(page);
  });

  test("desktop exposes primary workflow nav and advanced drill-downs", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto("/", { waitUntil: "networkidle" });

    const nav = page.getByRole("navigation", { name: "Sidebar navigation" });
    await expect(nav.getByRole("link", { name: "Upload", exact: true })).toHaveAttribute("href", "/upload");
    await expect(nav.getByRole("link", { name: "Reports" })).toHaveAttribute("href", "/reports");
    await expect(nav.getByRole("link", { name: "Chat", exact: true })).toHaveAttribute("href", "/chat");
    await expect(nav.getByRole("button", { name: /Advanced.*3/ })).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });

    await nav.getByRole("button", { name: /Advanced/ }).click();
    await expect(nav.getByRole("link", { name: "Portfolio" })).toHaveAttribute("href", "/portfolio");
    await expect(nav.getByRole("link", { name: "Reconciliation" })).toHaveAttribute("href", "/reconciliation");
    await expect(nav.getByRole("link", { name: "Processing" })).toHaveAttribute("href", "/processing");
    await expect(nav.getByRole("link", { name: "AI Settings" })).toHaveAttribute("href", "/settings/ai");
    await expectNoDocumentHorizontalScroll(page);
  });

  test("mobile exposes the same primary and advanced route access", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/", { waitUntil: "networkidle" });

    await page.getByLabel("Open navigation menu").click();
    const dialog = page.getByRole("dialog", { name: "Finance Report" });
    await expect(dialog.getByRole("link", { name: "Upload", exact: true })).toHaveAttribute("href", "/upload");
    await expect(dialog.getByRole("link", { name: "Reports" })).toHaveAttribute("href", "/reports");
    await expect(dialog.getByRole("link", { name: "Chat", exact: true })).toHaveAttribute("href", "/chat");

    await dialog.getByRole("button", { name: "Advanced" }).click();
    await expect(dialog.getByRole("link", { name: "Portfolio" })).toHaveAttribute("href", "/portfolio");
    await expect(dialog.getByRole("link", { name: "AI Settings" })).toHaveAttribute("href", "/settings/ai");
    await expectNoDocumentHorizontalScroll(page);
  });
});

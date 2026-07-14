import { expect, test, type Page } from "@playwright/test";

const COLD_ROUTE_TIMEOUT_MS = 10_000;

const workflowStatus = {
  primary_state: "needs_action",
  next_action: { type: "review_required", count: 2, href: "/statements/stmt-1/review" },
  report_readiness: { state: "blocked", blocking_count: 1, href: "/reports/package" },
  event_counts: { unread: 2, action_required: 1, blocked: 1 },
  active_session: {
    id: "inbox-session",
    status: "active",
    title: "Upload-to-report session",
    summary: "Current upload, processing, review, and report-readiness work.",
    started_at: "2026-06-04T01:00:00Z",
    last_event_at: "2026-06-04T02:00:00Z",
    source_count: 2,
    primary_state: "needs_action",
    report_readiness: { state: "blocked", blocking_count: 1, href: "/reports/package" },
    event_counts: { unread: 2, action_required: 1, blocked: 1 },
  },
};

const workflowEvents = {
  total: 2,
  sessions: [],
  items: [
    {
      id: "review-evt",
      user_id: "inbox-user",
      session_id: "inbox-session",
      occurred_at: "2026-06-04T08:00:00Z",
      family: "review.required",
      severity: "action_required",
      status: "unread",
      title: "Source review required",
      summary: "statement.pdf needs source review before report readiness can advance.",
      source_type: "bank_statement",
      source_id: "stmt-1",
      action_href: "/statements/stmt-1/review",
      report_impact: "blocked",
    },
    {
      id: "recon-evt",
      user_id: "inbox-user",
      session_id: "inbox-session",
      occurred_at: "2026-06-04T07:00:00Z",
      family: "reconciliation.blocked",
      severity: "blocked",
      status: "unread",
      title: "Reconciliation review required",
      summary: "Pending matches need review before reports are ready.",
      source_type: "reconciliation",
      source_id: "run-1",
      action_href: "/reconciliation/review-queue",
      report_impact: "blocked",
    },
  ],
};

async function installInboxMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("finance_user_id", "inbox-user");
    localStorage.setItem("finance_user_email", "inbox@example.com");
  });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};
    if (path === "/api/workflow/status") body = workflowStatus;
    else if (path === "/api/workflow/events") body = workflowEvents;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

async function expectNoDocumentHorizontalScroll(page: Page) {
  const metrics = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth);
}

test.describe("AC22.2.6 unified inbox smoke", () => {
  test.beforeEach(async ({ page }) => {
    await installInboxMocks(page);
  });

  for (const { label, width, height } of [
    { label: "desktop", width: 1440, height: 1000 },
    { label: "mobile", width: 390, height: 844 },
  ]) {
    // AC-platform.fe-ia-inbox.3
    test(`${label} surfaces review attention in the notification center with deep links`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await page.goto("/notifications", { waitUntil: "networkidle" });

      // Both Stage 1 review and Stage 2 reconciliation attention show in one place.
      await expect(page.getByText("Source review required").first()).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
      await expect(page.getByText("Reconciliation review required").first()).toBeVisible();

      // Each card deep-links to its specific follow-up surface.
      await expect(page.locator('a[href="/statements/stmt-1/review"]').first()).toBeVisible();
      await expect(page.locator('a[href="/reconciliation/review-queue"]').first()).toBeVisible();

      await expectNoDocumentHorizontalScroll(page);
    });
  }
});

import { expect, test, type Page } from "@playwright/test";

// AC22.4.5 — end-to-end everyday-user attention journey: from the Home shell,
// the notification center surfaces BOTH Stage 1 source-review and Stage 2
// reconciliation-review attention, each deep-linking to its detail surface.

const COLD_ROUTE_TIMEOUT_MS = 10_000;

const STMT_ID = "11111111-1111-4111-8111-111111111111";

const workflowStatus = {
  primary_state: "needs_action",
  next_action: { type: "review_required", count: 2, href: `/statements/${STMT_ID}/review` },
  report_readiness: { state: "blocked", blocking_count: 2, href: "/reports/package" },
  event_counts: { unread: 2, action_required: 1, blocked: 1 },
  active_session: {
    id: "attention-session",
    status: "active",
    title: "Upload-to-report session",
    summary: "Current upload, processing, review, and report-readiness work.",
    started_at: "2026-06-04T01:00:00Z",
    last_event_at: "2026-06-04T02:00:00Z",
    source_count: 2,
    primary_state: "needs_action",
    report_readiness: { state: "blocked", blocking_count: 2, href: "/reports/package" },
    event_counts: { unread: 2, action_required: 1, blocked: 1 },
  },
};

const workflowEvents = {
  total: 2,
  sessions: [],
  items: [
    {
      id: "stage1-review",
      user_id: "attn-user",
      session_id: "attention-session",
      occurred_at: "2026-06-04T08:00:00Z",
      family: "review.required",
      severity: "action_required",
      status: "unread",
      title: "Source review required",
      summary: "statement.pdf needs source review before report readiness can advance.",
      source_type: "bank_statement",
      source_id: STMT_ID,
      action_href: `/statements/${STMT_ID}/review`,
      report_impact: "blocked",
    },
    {
      id: "stage2-recon",
      user_id: "attn-user",
      session_id: "attention-session",
      occurred_at: "2026-06-04T07:00:00Z",
      family: "reconciliation.blocked",
      severity: "blocked",
      status: "unread",
      title: "Reconciliation blockers",
      summary: "Pending reconciliation matches must be accepted or rejected (2 items).",
      source_type: "readiness_blocker",
      source_id: "22222222-2222-4222-8222-222222222222",
      action_href: "/reconciliation/review-queue",
      report_impact: "blocked",
    },
  ],
};

async function installMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("finance_user_id", "attn-user");
    localStorage.setItem("finance_user_email", "attn@example.com");
  });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};
    if (path === "/api/workflow/status") body = workflowStatus;
    else if (path === "/api/workflow/events") body = workflowEvents;
    else if (path === "/api/assets/restricted") body = [];
    else if (path === "/api/reconciliation/unmatched") body = { items: [], total: 0 };
    else if (path.startsWith("/api/journal-entries")) body = { items: [], total: 0 };
    else if (path === "/api/accounts") body = { items: [], total: 0 };
    else if (path === "/api/statements") body = { items: [], total: 0 };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

test.describe("AC22.4.5 everyday-user attention journey", () => {
  test.beforeEach(async ({ page }) => {
    await installMocks(page);
  });

  for (const { label, width, height } of [
    { label: "desktop", width: 1440, height: 1000 },
    { label: "mobile", width: 390, height: 844 },
  ]) {
    // AC-reconciliation.fe-ia-reconciliation.2
    test(`${label}: both Stage 1 and Stage 2 attention surface in the notification center with deep links`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height });

      // Open the dedicated notification center (also reached via the header bell).
      await page.goto("/notifications", { waitUntil: "networkidle" });

      await expect(page.getByText("Source review required").first()).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
      await expect(page.getByText("Reconciliation blockers").first()).toBeVisible();

      // Stage 1 deep-links to the specific statement review; Stage 2 to the queue.
      await expect(page.locator(`a[href="/statements/${STMT_ID}/review"]`).first()).toBeVisible();
      await expect(page.locator('a[href="/reconciliation/review-queue"]').first()).toBeVisible();
    });
  }
});

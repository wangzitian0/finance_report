import { expect, test, type Page } from "@playwright/test";

// #2648: the upload page of the LE review on staging v0.2.29. Approved bank statements from July to
// September, the October statement at 80 %, and a brokerage positions file whose import returned
// HTTP 500. The workflow status reports the blocker of the old 1Y window and one review item. The
// file names are long tokens without spaces, as broker exports are: they must wrap, not widen the page.

const COLD_ROUTE_TIMEOUT_MS = 10_000;
const BROKERAGE_ID = "2648a0b1-0000-4000-8000-0000000b0001";
// The 422 reason of #2649 for a source without an as-of date: the upload list states it (#2648).
const IMPORT_FAILURE =
  "The positions source does not state an as-of date for 2 of 2 positions. The import needs the date that the source states.";

const statementRow = (id: string, filename: string, status: string, extra: Record<string, unknown> = {}) => ({
  id,
  user_id: "upload-layout-user",
  account_id: "acct-dbs",
  file_path: `statements/${filename}`,
  original_filename: filename,
  institution: "DBS",
  account_last4: "4471",
  currency: "SGD",
  period_start: "2026-07-01",
  period_end: "2026-07-31",
  opening_balance: "1000.00",
  closing_balance: "1200.00",
  status,
  confidence_score: 98,
  balance_validated: true,
  validation_error: null,
  brokerage_import_failed: false,
  brokerage_import_failure_reason: null,
  created_at: "2026-10-23T00:00:00Z",
  updated_at: "2026-10-23T00:00:00Z",
  transactions: [],
  ...extra,
});

const STATEMENTS = [
  statementRow(BROKERAGE_ID, "Interactive_Brokers_Positions_U1234567_20261031.csv", "parsed", {
    institution: "Interactive Brokers",
    account_id: null,
    account_last4: null,
    currency: null,
    period_start: null,
    period_end: null,
    opening_balance: null,
    closing_balance: null,
    confidence_score: 20,
    balance_validated: null,
    validation_error: null,
    brokerage_import_failed: true,
    brokerage_import_failure_reason: IMPORT_FAILURE,
  }),
  statementRow("2648a0b1-0000-4000-8000-000000000010", "dbs-2026-10.csv", "parsed", {
    period_start: "2026-10-01",
    period_end: "2026-10-31",
    confidence_score: 80,
  }),
  statementRow("2648a0b1-0000-4000-8000-000000000009", "dbs-2026-09.csv", "approved", { period_start: "2026-09-01", period_end: "2026-09-30" }),
  statementRow("2648a0b1-0000-4000-8000-000000000008", "dbs-2026-08.csv", "approved", { period_start: "2026-08-01", period_end: "2026-08-31" }),
  statementRow("2648a0b1-0000-4000-8000-000000000007", "dbs-2026-07.csv", "approved"),
];

const event = (id: string, severity: string, title: string, summary: string, actionHref: string) => ({
  id,
  user_id: "upload-layout-user",
  session_id: "session-1",
  occurred_at: "2026-10-23T04:05:00Z",
  family: `${severity}.event`,
  severity,
  status: "unread",
  title,
  summary,
  source_type: "bank_statement",
  source_id: id,
  action_href: actionHref,
  report_impact: severity === "blocked" ? "blocked" : "ready",
  dedupe_key: id,
  created_at: "2026-10-23T04:05:00Z",
  updated_at: "2026-10-23T04:05:00Z",
});

const EVENTS = [
  event(
    "evt-blocker",
    "blocked",
    "Package section invariant failed",
    "Your statements start after the first day of this period. Upload the earlier statements or choose a period that starts on or after your first statement.",
    "/reports?tab=package",
  ),
  event("evt-review", "action_required", "Review required for Interactive_Brokers_Activity_Statement_U1234567_20261001_20261031.csv", "Confirm one low-confidence statement extraction.", "/statements/2648a0b1-0000-4000-8000-000000000010"),
  event("evt-posted", "success", "Safe entries posted", "Automation posted high-confidence entries.", "/journal"),
];

async function installMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("finance_user_id", "upload-layout-user");
    localStorage.setItem("finance_user_email", "upload-layout@example.com");
  });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = { items: [], total: 0 };
    if (path === "/api/statements") body = { items: STATEMENTS, total: STATEMENTS.length };
    else if (path === "/api/workflow/status") {
      body = {
        primary_state: "blocked",
        next_action: { type: "resolve_blocker", count: 1, href: "/reports?tab=package", label: "Resolve the blocking condition", summary: "" },
        report_readiness: { state: "blocked", blocking_count: 1, href: "/reports?tab=package" },
        event_counts: { unread: 3, action_required: 1, blocked: 1 },
        active_session: null,
      };
    } else if (path === "/api/workflow/events") body = { items: EVENTS, total: EVENTS.length, sessions: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

const brokerageRow = (page: Page) => page.getByTestId(`upload-statement-row-${BROKERAGE_ID}`);

test.describe("#2648 upload page", () => {
  test.beforeEach(async ({ page }) => {
    await installMocks(page);
  });

  // AC-extraction.fe-upload-layout.1
  test("AC-extraction.fe-upload-layout.1 has no horizontal overflow at 375 px", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/upload", { waitUntil: "networkidle" });
    await expect(brokerageRow(page)).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });

    const measure = () =>
      page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        // The widest element that crosses the right edge, for the failure message.
        widest: [...document.querySelectorAll("body *")]
          .map((element) => ({ element, right: element.getBoundingClientRect().right }))
          .filter(({ right }) => right > document.documentElement.clientWidth + 0.5)
          .sort((a, b) => b.right - a.right)
          .slice(0, 3)
          .map(({ element, right }) => `${element.tagName.toLowerCase()}.${String(element.className).slice(0, 60)} right=${Math.round(right)}`),
      }));
    const folded = await measure();
    expect(folded.scrollWidth, `scrollWidth, details folded; widest: ${folded.widest.join(" | ")}`).toBeLessThanOrEqual(375);

    // The workflow details hold the long file names: they wrap when the user opens them.
    await page.getByTestId("upload-workflow-summary").locator(":scope > summary").click();
    await expect(page.getByText("Package section invariant failed")).toBeVisible();
    const open = await measure();
    expect(open.scrollWidth, `scrollWidth, details open; widest: ${open.widest.join(" | ")}`).toBeLessThanOrEqual(375);
  });

  // AC-extraction.fe-upload-layout.2
  test("AC-extraction.fe-upload-layout.2 starts the file list within 1.5 viewports at 375x812", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/upload", { waitUntil: "networkidle" });
    const list = page.locator("#statements");
    await expect(brokerageRow(page)).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
    const top = await list.evaluate((element) => element.getBoundingClientRect().top + window.scrollY);
    expect(top, "file list top in CSS px").toBeLessThanOrEqual(812 * 1.5);

    // The workflow details are folded under a one-line summary.
    const summary = page.getByTestId("upload-workflow-summary");
    await expect(summary).toBeVisible();
    await expect(summary).toContainText("1 blocker");
    await expect(page.getByText("Package section invariant failed")).toBeHidden();
  });

  for (const { label, width, height } of [
    { label: "mobile", width: 375, height: 812 },
    { label: "desktop", width: 1280, height: 800 },
  ]) {
    // AC-extraction.fe-upload-layout.3
    test(`AC-extraction.fe-upload-layout.3 shows a failed import as Import failed with Retry and Delete (${label})`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      let retried = false;
      await page.route(`**/api/statements/${BROKERAGE_ID}/brokerage/import`, async (route) => {
        retried = true;
        await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "internal", error_id: "internal_error" }) });
      });
      await page.goto("/upload", { waitUntil: "networkidle" });

      const row = brokerageRow(page);
      await expect(row).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
      await expect(row.getByText("Import failed", { exact: true })).toBeVisible();
      await expect(row).toContainText("does not state an as-of date for 2 of 2 positions");
      await expect(row.getByRole("button", { name: "Delete Statement" })).toBeVisible();
      for (const forbidden of ["Parsing", "Ready to review", "Review & Approve"]) {
        await expect(row.getByText(forbidden), forbidden).toHaveCount(0);
      }

      await row.getByRole("button", { name: "Retry import" }).click();
      await expect.poll(() => retried).toBe(true);
      // A second failure keeps the row in the failed state.
      await expect(row.getByText("Import failed", { exact: true })).toBeVisible();
    });
  }
});

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
  statementRow("2648a0b1-0000-4000-8000-000000000011", "cmb_statement_fixture.pdf", "parsed", {
    institution: "GXS Bank",
    period_start: "2025-03-01",
    period_end: "2025-03-31",
    currency: "SGD",
    confidence_score: 85,
  }),
  statementRow("2648a0b1-0000-4000-8000-000000000012", "gxs_approved_statement_202503.pdf", "approved", {
    institution: "GXS Bank",
    period_start: "2025-03-01",
    period_end: "2025-03-31",
    currency: "SGD",
    confidence_score: 98,
  }),
  statementRow("2648a0b1-0000-4000-8000-000000000013", "cny_parsing_statement_202610.pdf", "parsing", {
    institution: "CMB",
    period_start: null,
    period_end: null,
    currency: "CNY",
    opening_balance: "0.00",
    closing_balance: "0.00",
    confidence_score: null,
    balance_validated: null,
  }),
];

const TRANSFERS = [
  {
    entry_id: "tf-1",
    from_account: "DBS Multiplier ••4471",
    to_account: "(unmatched destination) GXS Bank ••9912",
    amount: "1500.00",
    currency: "SGD",
    initiated_date: "2026-10-20",
    days_outstanding: 9,
    description: "FAST Transfer to GXS",
  },
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
    else if (path === "/api/accounts/processing/pending") body = { items: TRANSFERS, total: TRANSFERS.length };
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
    await expect(page.getByText("Statement balance check needed").first()).toBeVisible();
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
    await expect(page.getByText("Statement balance check needed").first()).toBeHidden();
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

  // AC-extraction.fe-upload-layout.6
  test("AC-extraction.fe-upload-layout.6 stacks mobile upload cards and transfers without overlap or clipping at 390x844", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/upload", { waitUntil: "networkidle" });

    const approvedRow = page.getByTestId("upload-statement-row-2648a0b1-0000-4000-8000-000000000012");
    await expect(approvedRow).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
    const approvedBadge = approvedRow.getByText("Approved", { exact: true });
    const viewTxnsBtn = approvedRow.getByRole("button", { name: "View Transactions" });
    const badgeBox = await approvedBadge.boundingBox();
    const btnBox = await viewTxnsBtn.boundingBox();
    expect(badgeBox).not.toBeNull();
    expect(btnBox).not.toBeNull();
    const overlaps =
      badgeBox!.x < btnBox!.x + btnBox!.width &&
      badgeBox!.x + badgeBox!.width > btnBox!.x &&
      badgeBox!.y < btnBox!.y + btnBox!.height &&
      badgeBox!.y + badgeBox!.height > btnBox!.y;
    expect(overlaps, "Approved badge must not overlap View Transactions button").toBe(false);

    // Metadata line must not wrap into a narrow 1-word vertical column (height <= 2 lines, i.e. <= 44px).
    const metaBox = await approvedRow.getByText("2025-03-01 to 2025-03-31").boundingBox();
    expect(metaBox?.height ?? 999, "metadata period height in px").toBeLessThanOrEqual(40);

    // Ready to review card filename displays at least 18 characters width (>= 140px before truncation).
    const readyRow = page.getByTestId("upload-statement-row-2648a0b1-0000-4000-8000-000000000011");
    const titleBox = await readyRow.getByRole("link", { name: "cmb_statement_fixture.pdf" }).boundingBox();
    expect(titleBox?.width ?? 0, "filename link width at 390px").toBeGreaterThanOrEqual(140);

    // Parsing card hides Opening: 0.00 / Closing: 0.00 / confidence placeholders.
    const parsingRow = page.getByTestId("upload-statement-row-2648a0b1-0000-4000-8000-000000000013");
    await expect(parsingRow).toBeVisible();
    await expect(parsingRow.getByText(/Opening:/)).toHaveCount(0);
    await expect(parsingRow.getByText(/Closing:/)).toHaveCount(0);
    await expect(parsingRow.getByText(/confidence/i)).toHaveCount(0);

    // Transfers in flight renders full From and To text without right-edge clipping at 390px.
    const transfers = page.getByRole("region", { name: "Transfers in flight" });
    await expect(transfers).toBeVisible();
    const toText = transfers.getByText("(unmatched destination) GXS Bank ••9912").first();
    await expect(toText).toBeVisible();
    const toBox = await toText.boundingBox();
    expect((toBox?.x ?? 0) + (toBox?.width ?? 999), "To account right edge <= 390px").toBeLessThanOrEqual(390);
  });
});

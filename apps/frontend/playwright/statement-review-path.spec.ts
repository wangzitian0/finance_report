import { expect, test, type Page } from "@playwright/test";

// #2586: the staging gate tests/e2e/test_vision_upload_to_dashboard_hard_gate.py opens the review page
// through this click path: upload list -> statement detail -> "Start Review →". Only staging ran that
// path, so a page change that broke it failed after the deploy (#2577). This spec runs the same click
// path and locators against a mocked API on each frontend PR.

const COLD_ROUTE_TIMEOUT_MS = 10_000;
const STMT_ID = "2586a0b1-0000-4000-8000-000000002586";

// The state of the staging step: a parsed CSV with no custody account and no confirmed source envelope.
const statement = {
  id: STMT_ID,
  user_id: "review-path-user",
  account_id: null,
  file_path: null,
  file_hash: "f".repeat(64),
  original_filename: "vision_hard_gate_statement.csv",
  institution: "Generic Vision Hard Gate",
  account_last4: null,
  currency: "SGD",
  period_start: "2026-05-01",
  period_end: "2026-05-31",
  opening_balance: "0.00",
  closing_balance: "0.00",
  status: "parsed",
  stage1_status: "pending_review",
  confidence_score: 80,
  balance_validated: true,
  validation_error: null,
  created_at: "2026-05-31T00:00:00Z",
  updated_at: "2026-05-31T00:00:00Z",
  transactions: [
    {
      id: "2586a0b1-0000-4000-8000-0000000000t1",
      statement_id: STMT_ID,
      txn_date: "2026-05-02",
      description: "Salary",
      reference: null,
      amount: "5000.00",
      direction: "IN",
      currency: "SGD",
      balance_after: null,
      confidence: "low",
      status: "pending",
    },
  ],
  source_result_digest: "a".repeat(64),
  source_missing_facts: [],
  source_envelope_reviewable: true,
  reviewed_envelope: null,
};

// #2647: the October statement of the LE review. Six rows; the LOW row is the last row of the source.
const OCTOBER_ID = "2647a0b1-0000-4000-8000-000000002647";
const PDF_ID = "2647a0b1-0000-4000-8000-0000000002f0";
const APPROVED_ID = "2647a0b1-0000-4000-8000-0000000002a0";
const LOW_DESCRIPTION = "PayNow Transfer REF 4471";
const octoberRow = (index: number, description: string, tier: "HIGH" | "MEDIUM" | "LOW", amount: string, direction: "IN" | "OUT") => ({
  id: `2647a0b1-0000-4000-8000-00000000000${index}`,
  statement_id: OCTOBER_ID,
  txn_date: `2026-10-0${index}`,
  description,
  reference: null,
  amount,
  direction,
  currency: "SGD",
  balance_after: null,
  confidence_tier: tier,
  confidence_score: tier === "LOW" ? 35 : 92,
  created_at: "2026-10-31T00:00:00Z",
  updated_at: "2026-10-31T00:00:00Z",
});
const OCTOBER_ROWS = [
  octoberRow(1, "Salary credit ACME PTE LTD", "HIGH", "5000.00", "IN"),
  octoberRow(2, "NTUC FairPrice Toa Payoh", "HIGH", "84.20", "OUT"),
  octoberRow(3, "Grab ride", "MEDIUM", "18.40", "OUT"),
  octoberRow(4, "SP Group utilities", "HIGH", "120.55", "OUT"),
  octoberRow(5, "Rent October", "HIGH", "2200.00", "OUT"),
  octoberRow(6, LOW_DESCRIPTION, "LOW", "250.00", "OUT"),
];
const october = {
  ...statement,
  id: OCTOBER_ID,
  original_filename: "dbs-2026-10.csv",
  file_path: "statements/dbs-2026-10.csv",
  period_start: "2026-10-01",
  period_end: "2026-10-31",
  transactions: OCTOBER_ROWS,
};
const STATEMENTS: Record<string, unknown> = {
  [STMT_ID]: statement,
  [OCTOBER_ID]: october,
  [PDF_ID]: { ...october, id: PDF_ID, original_filename: "dbs-2026-10.pdf", file_path: "statements/dbs-2026-10.pdf" },
  [APPROVED_ID]: { ...october, id: APPROVED_ID, status: "approved", stage1_status: "approved", account_id: "acct-dbs", reviewed_envelope: {} },
};

async function installMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("finance_user_id", "review-path-user");
    localStorage.setItem("finance_user_email", "review-path@example.com");
  });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const [, , , id, rest] = path.split("/");
    let body: unknown = {};
    if (path === "/api/statements") body = { items: [{ ...statement, transactions: [] }], total: 1 };
    else if (path.startsWith("/api/statements/") && id in STATEMENTS && (rest === undefined || rest === "review")) body = STATEMENTS[id];
    else if (path === "/api/statements/pending-review") body = { items: [statement], total: 1 };
    else if (path.startsWith("/api/review/conflicts/")) body = { duplicates: [], transfer_pairs: [] };
    else if (path === "/api/accounts") body = { items: [], total: 0 };
    else if (path === "/api/workflow/events") body = { items: [], total: 0, sessions: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

test.describe("AC-extraction.human-source-review.4 statement review click path", () => {
  test.beforeEach(async ({ page }) => {
    await installMocks(page);
  });

  test("upload list -> statement page shows a disabled Approve", async ({ page }) => {
    await page.goto("/upload", { waitUntil: "networkidle" });
    const statementLink = page.locator(`a[href="/statements/${STMT_ID}"]`);
    await expect(statementLink).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
    await statementLink.click();
    await expect(page).toHaveURL(new RegExp(`/statements/${STMT_ID}$`), { timeout: COLD_ROUTE_TIMEOUT_MS });

    // The statement page is the review page: there is no separate review link to follow.
    await expect(page.locator(`a[href="/statements/${STMT_ID}/review"]`)).toHaveCount(0);

    // Without a confirmed source envelope and a custody account, the statement page blocks approval.
    await expect(page.getByText("Confirm source facts")).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
    await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
  });

  // AC-extraction.fe-stage1-review.22
  test("AC-extraction.fe-stage1-review.22 keeps the description readable in a CSV statement at 1280 px", async ({ page }) => {
    // #2621: the side-by-side table had fixed columns of 512 px in a 544 px table, so the description
    // column had no width and the staging journey could not see a transaction row. Since #2647 a CSV
    // source has no preview panel; the PDF variant below keeps the side-by-side case.
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(`/statements/${STMT_ID}`, { waitUntil: "networkidle" });
    const region = page.getByTestId("stage1-desktop-transaction-region");
    const description = region.getByTitle("Salary", { exact: true });
    await expect(description).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
    const box = await description.boundingBox();
    expect(box?.width ?? 0, "description column content width in px").toBeGreaterThanOrEqual(120);
    await expect(region).toHaveCSS("overflow-y", "auto");
  });

  // AC-extraction.fe-stage1-review.22
  test("AC-extraction.fe-stage1-review.22 keeps the description readable beside a PDF preview at 1280 px", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(`/statements/${PDF_ID}`, { waitUntil: "networkidle" });
    await expect(page.getByRole("heading", { name: "PDF Preview" })).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
    const region = page.getByTestId("stage1-desktop-transaction-region");
    const description = region.getByTitle(LOW_DESCRIPTION, { exact: true });
    await expect(description).toBeVisible();
    const box = await description.boundingBox();
    expect(box?.width ?? 0, "description column content width in px").toBeGreaterThanOrEqual(120);
    await expect(region).toHaveCSS("overflow-y", "auto");
  });

  for (const { label, width, height, id, preview } of [
    { label: "CSV, desktop", width: 1280, height: 800, id: OCTOBER_ID, preview: false },
    { label: "CSV, mobile", width: 375, height: 812, id: OCTOBER_ID, preview: false },
    // The narrowest description column: beside a PDF preview. The LE review saw "PayNow Transfe…" here.
    { label: "PDF, desktop", width: 1280, height: 800, id: PDF_ID, preview: true },
  ]) {
    // AC-extraction.fe-stage1-review.26
    test(`AC-extraction.fe-stage1-review.26 puts the low row first and in full on one page scroll (${label})`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await page.goto(`/statements/${id}`, { waitUntil: "networkidle" });

      const firstRow =
        width >= 1280
          ? page.getByTestId("stage1-desktop-transaction-region").locator("tbody tr").first()
          : page.getByTestId("stage1-mobile-transaction-list").locator("article").first();
      await expect(firstRow).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
      await expect(firstRow).toContainText(LOW_DESCRIPTION);
      // The pinned row states its source position: it is the last row of the source.
      await expect(firstRow.getByTestId("source-row-number")).toHaveText("Row 6");
      await expect(page.getByTestId("low-confidence-count")).toHaveText("1 low confidence · shown first");

      // The description renders in full: the text fits its box and no ellipsis clips it.
      const text = firstRow.getByText(LOW_DESCRIPTION, { exact: true });
      const fit = await text.evaluate((element) => ({
        text: element.textContent,
        textOverflow: getComputedStyle(element).textOverflow,
        scrollWidth: element.scrollWidth,
        clientWidth: element.clientWidth,
      }));
      expect(fit.text).toBe(LOW_DESCRIPTION);
      expect(fit.textOverflow).not.toBe("ellipsis");
      expect(fit.scrollWidth, "description scroll width <= client width").toBeLessThanOrEqual(fit.clientWidth);

      // A CSV source has no preview panel. A PDF source keeps it.
      await expect(page.getByRole("heading", { name: "PDF Preview" })).toHaveCount(preview ? 1 : 0);

      if (width < 768) {
        // One page scroll: the mobile list has no inner scroll box.
        const list = page.getByTestId("stage1-mobile-transaction-list");
        const scroll = await list.evaluate((element) => ({ scrollHeight: element.scrollHeight, clientHeight: element.clientHeight }));
        expect(scroll.scrollHeight, "mobile list scrollHeight = clientHeight").toBe(scroll.clientHeight);
        await expect(list.locator("article")).toHaveCount(OCTOBER_ROWS.length);
      }
    });

  }

  for (const { label, width, height } of [
    { label: "desktop", width: 1280, height: 800 },
    { label: "mobile", width: 375, height: 812 },
  ]) {
    // AC-extraction.fe-stage1-review.24
    test(`AC-extraction.fe-stage1-review.24 shows no pending chip on an approved statement (${label})`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await page.goto(`/statements/${APPROVED_ID}`, { waitUntil: "networkidle" });
      const region = page.getByTestId("stage1-desktop-transaction-region");
      await expect(region.getByTitle(LOW_DESCRIPTION, { exact: true })).toBeAttached({ timeout: COLD_ROUTE_TIMEOUT_MS });
      await expect(page.getByText("pending", { exact: true })).toHaveCount(0);
    });
  }
});

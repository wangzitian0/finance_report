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

async function installMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("finance_user_id", "review-path-user");
    localStorage.setItem("finance_user_email", "review-path@example.com");
  });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};
    if (path === "/api/statements") body = { items: [{ ...statement, transactions: [] }], total: 1 };
    else if (path === `/api/statements/${STMT_ID}`) body = statement;
    else if (path === `/api/statements/${STMT_ID}/review`) body = statement;
    else if (path === "/api/statements/pending-review") body = { items: [statement], total: 1 };
    else if (path === `/api/review/conflicts/${STMT_ID}`) body = { duplicates: [], transfer_pairs: [] };
    else if (path === "/api/accounts") body = { items: [], total: 0 };
    else if (path === "/api/workflow/events") body = { items: [], total: 0, sessions: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

test.describe("AC-extraction.human-source-review.4 statement review click path", () => {
  test.beforeEach(async ({ page }) => {
    await installMocks(page);
  });

  test("upload list -> statement detail -> Start Review shows a disabled Approve", async ({ page }) => {
    await page.goto("/upload", { waitUntil: "networkidle" });
    const reviewPath = `/statements/${STMT_ID}/review`;

    const statementLink = page.locator(`a[href="/statements/${STMT_ID}"]`);
    await expect(statementLink).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
    await statementLink.click();
    await expect(page).toHaveURL(new RegExp(`/statements/${STMT_ID}$`), { timeout: COLD_ROUTE_TIMEOUT_MS });

    const reviewLink = page.getByRole("link", { name: "Start Review →", exact: true });
    await expect(reviewLink).toHaveAttribute("href", reviewPath, { timeout: COLD_ROUTE_TIMEOUT_MS });
    await reviewLink.click();
    await expect(page).toHaveURL(new RegExp(`${reviewPath}$`), { timeout: COLD_ROUTE_TIMEOUT_MS });

    // Without a confirmed source envelope and a custody account, the review page blocks approval.
    await expect(page.getByText("Confirm source facts")).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
    await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
  });
});

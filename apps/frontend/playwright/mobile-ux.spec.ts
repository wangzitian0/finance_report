import { expect, test, type Page } from "@playwright/test";

const COLD_ROUTE_TIMEOUT_MS = 10_000;

const baseEntry = {
  id: "entry-mobile",
  entry_date: "2026-06-01",
  status: "posted",
  source_type: "manual_adjustment",
  memo: "Mobile review sample entry",
  created_at: "2026-06-01T08:00:00Z",
  lines: [
    {
      id: "line-debit",
      account_id: "assets:cash:very-long-account-identifier-for-mobile",
      direction: "DEBIT",
      amount: "123456.78",
      currency: "SGD",
    },
    {
      id: "line-credit",
      account_id: "income:salary:very-long-account-identifier-for-mobile",
      direction: "CREDIT",
      amount: "123456.78",
      currency: "SGD",
    },
  ],
};

const baseStatementReview = {
  id: "stmt-mobile",
  account_id: "account-mobile",
  original_filename: "very-long-mobile-statement-name-june-2026.pdf",
  institution: "Mobile Bank",
  account_last4: "1234",
  currency: "SGD",
  period_start: "2026-06-01",
  period_end: "2026-06-30",
  opening_balance: "1000.00",
  closing_balance: "1123.45",
  status: "pending_review",
  stage1_status: "pending_review",
  balance_validation_result: {
    opening_balance: "1000.00",
    closing_balance: "1123.45",
    calculated_closing: "1123.45",
    opening_delta: "0.00",
    closing_delta: "0.00",
    opening_match: true,
    closing_match: true,
    validated_at: "2026-06-30T08:00:00Z",
  },
  pdf_url: null,
  transactions: [
    {
      id: "txn-mobile-1",
      txn_date: "2026-06-05",
      description: "Long mobile grocery transaction from a bank statement",
      amount: "123.45",
      direction: "OUT",
      currency: "SGD",
      confidence: "medium",
      confidence_tier: "medium",
    },
  ],
};

const baseStage2Queue = {
  pending_matches: [
    {
      id: "match-mobile-1",
      match_score: 91,
      status: "pending_review",
      created_at: "2026-06-01T08:00:00Z",
      description: "Long reconciliation match needing mobile approval",
      amount: "123.45",
      txn_date: "2026-06-05",
    },
  ],
  consistency_checks: [],
  has_unresolved_checks: false,
};

const baseAccounts = {
  items: [
    {
      id: "account-mobile-long",
      name: "DBS Multiplier Main Operating Account With Long Name",
      code: "1010",
      type: "ASSET",
      currency: "SGD",
      balance: "123456.78",
      is_active: true,
      description: "Primary cash account used for statement imports",
    },
    {
      id: "income-mobile",
      name: "Salary Income",
      code: "4010",
      type: "INCOME",
      currency: "SGD",
      balance: "0.00",
      is_active: true,
      description: "Monthly employment income",
    },
  ],
  total: 2,
};

async function installMobileApiMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("finance_user_id", "mobile-user");
    localStorage.setItem("finance_user_email", "mobile@example.com");
  });

  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};

    if (path === "/api/ai/suggestions") {
      body = {
        items: [
          {
            suggestion_id: "suggestion-mobile",
            transaction: "Long mobile transaction description from a bank statement",
            suggested_category_or_match: "Meals and entertainment",
            ai_score: 72,
            ai_reasoning: "Merchant category and prior corrections suggest this classification.",
          },
        ],
      };
    } else if (path.startsWith("/api/journal-entries")) {
      body = { items: [baseEntry], total: 1 };
    } else if (path.startsWith("/api/transactions/") && path.endsWith("/audit")) {
      body = { items: [] };
    } else if (path === "/api/statements/pending-review") {
      body = { items: [{ id: "stmt-mobile" }], total: 1 };
    } else if (path === "/api/statements/stmt-mobile/review") {
      body = baseStatementReview;
    } else if (path === "/api/statements/stmt-mobile/review/edit") {
      body = { success: true };
    } else if (path === "/api/statements/stmt-mobile/review/approve") {
      body = { journal_entries_created: 1 };
    } else if (path === "/api/statements/stmt-mobile/review/reject") {
      body = { success: true };
    } else if (path === "/api/statements/stage2/queue") {
      body = baseStage2Queue;
    } else if (path === "/api/statements/batch-approve-matches") {
      body = { success: true, approved_count: 1 };
    } else if (path === "/api/statements/batch-reject-matches") {
      body = { success: true, rejected_count: 1 };
    } else if (path === "/api/accounts/processing/summary") {
      body = {
        pending_count: 0,
        pending_total: "0.00",
        currency: "SGD",
        oldest_pending_date: null,
      };
    } else if (path === "/api/accounts") {
      body = baseAccounts;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
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

async function expectNoLocalHorizontalScroll(page: Page, testId: string) {
  const metrics = await page.getByTestId(testId).evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));

  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth);
}

async function gotoReady(page: Page, path: string) {
  await page.goto(path, { waitUntil: "networkidle" });
}

test.use({
  viewport: { width: 390, height: 844 },
  isMobile: true,
  hasTouch: true,
});

test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => {
  await installMobileApiMocks(page);
});

// AC-reconciliation.fe-stage2-review.12
test("AC16.25.1 mobile review routes avoid document horizontal scrolling", async ({ page }) => {
  await gotoReady(page, "/review/ai-suggestions");
  await expect(page.getByTestId("ai-suggestions-mobile-list")).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
  await expectNoDocumentHorizontalScroll(page);
  // The mobile bottom tab bar is always present and must not cause overflow.
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  await expectNoDocumentHorizontalScroll(page);

  await gotoReady(page, "/journal");
  await page.getByText("Mobile review sample entry").click();
  await expect(page.getByTestId("journal-lines-mobile")).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
  await expectNoDocumentHorizontalScroll(page);
});

// AC-reconciliation.fe-stage2-review.13
test("AC16.25.2 AI suggestions mobile cards expose feedback actions", async ({ page }) => {
  await gotoReady(page, "/review/ai-suggestions");

  const card = page.getByTestId("ai-suggestion-mobile-card-suggestion-mobile");
  await expect(card).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
  await expect(card.getByText("Long mobile transaction description")).toBeVisible();
  await expect(card.getByLabel("Corrected value")).toBeVisible();
  await expect(card.getByRole("button", { name: "Accept", exact: true })).toBeVisible();
  await expect(card.getByRole("button", { name: "Reject", exact: true })).toBeVisible();
  await expect(card.getByRole("button", { name: "Edit-then-Accept", exact: true })).toBeVisible();
  await expectNoDocumentHorizontalScroll(page);
});

// AC-extraction.fe-stage1-review.10
test("AC16.26.1 stage 1 mobile review exposes read-only transaction cards and completion actions", async ({ page }) => {
  await gotoReady(page, "/statements/stmt-mobile/review");

  await expect(page.getByTestId("stage1-mobile-transaction-card-txn-mobile-1")).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
  // Parsed transactions are read-only (EPIC-011 Stage 3 removed inline editing; a mis-parse
  // is corrected via reject + re-parse), so there are no per-field inputs or edit/discard buttons.
  await expect(page.getByLabel("Description for txn-mobile-1")).toHaveCount(0);
  await expect(page.getByLabel("Amount for txn-mobile-1")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Approve Edits (1)" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Reject", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeVisible();
  await expectNoDocumentHorizontalScroll(page);
});

test("AC16.26.2 stage 2 mobile queue exposes selectable match cards and batch actions", async ({ page }) => {
  await gotoReady(page, "/reconciliation/review-queue");

  const card = page.getByTestId("stage2-mobile-match-card-match-mobile-1");
  await expect(card).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
  await expect(card.getByText("Long reconciliation match needing mobile approval")).toBeVisible();
  await card.getByRole("checkbox", { name: "Select match match-mobile-1" }).check();
  await expect(page.getByRole("button", { name: "Reject", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve Selected", exact: true })).toBeVisible();
  await expectNoDocumentHorizontalScroll(page);
});

test("AC16.26.3 stage 2 run review preserves mobile approval gate and match workflow", async ({ page }) => {
  await gotoReady(page, "/review/run/run-mobile-1");

  await expect(page.getByText("Run approval gate")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve Run", exact: true })).toBeVisible();
  await expect(page.getByTestId("stage2-mobile-match-card-match-mobile-1")).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
  await expectNoDocumentHorizontalScroll(page);
});

// AC-ledger.fe-accounts2.1
test("AC2.17.1 mobile accounts avoids document horizontal scroll and overlapping row controls", async ({ page }) => {
  await gotoReady(page, "/accounts");

  await expect(page.getByRole("heading", { name: "Accounts" })).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
  await expect(page.getByTestId("account-row-account-mobile-long")).toBeVisible();
  await expectNoDocumentHorizontalScroll(page);

  const rowMetrics = await page.getByTestId("account-row-account-mobile-long").evaluate((row) => {
    const name = row.querySelector("[data-account-field='identity']")?.getBoundingClientRect();
    const balance = row.querySelector("[data-account-field='balance']")?.getBoundingClientRect();
    const actions = row.querySelector("[data-account-field='actions']")?.getBoundingClientRect();
    return {
      hasTargets: Boolean(name && balance && actions),
      nameBottom: name?.bottom ?? 0,
      balanceTop: balance?.top ?? 0,
      balanceBottom: balance?.bottom ?? 0,
      actionsTop: actions?.top ?? 0,
    };
  });

  expect(rowMetrics.hasTargets).toBe(true);
  expect(rowMetrics.nameBottom).toBeLessThanOrEqual(rowMetrics.balanceTop);
  expect(rowMetrics.balanceBottom).toBeLessThanOrEqual(rowMetrics.actionsTop);
});

test.describe("375px mobile review proof", () => {
  test.use({
    viewport: { width: 375, height: 812 },
    isMobile: true,
    hasTouch: true,
  });

  // AC-testing.fe-coverage.2
  test("AC8.13.76 stage 1 and stage 2 review routes remain usable at 375px", async ({ page }) => {
    await gotoReady(page, "/statements/stmt-mobile/review");
    await expect(page.getByTestId("stage1-mobile-transaction-card-txn-mobile-1")).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
    await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeVisible();
    await expectNoDocumentHorizontalScroll(page);

    await gotoReady(page, "/reconciliation/review-queue");
    await expect(page.getByTestId("stage2-mobile-match-card-match-mobile-1")).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
    await expect(page.getByRole("button", { name: "Approve Selected", exact: true })).toBeVisible();
    await expectNoDocumentHorizontalScroll(page);

    await gotoReady(page, "/review/run/run-mobile-1");
    await expect(page.getByRole("button", { name: "Approve Run", exact: true })).toBeVisible();
    await expect(page.getByTestId("stage2-mobile-match-card-match-mobile-1")).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
    await expectNoDocumentHorizontalScroll(page);
  });
});

test.describe("1440px desktop review proof", () => {
  test.use({
    viewport: { width: 1440, height: 1000 },
    isMobile: false,
    hasTouch: false,
  });

  // AC-extraction.fe-stage1-review.11
  // AC-testing.fe-coverage.3
  test("AC8.13.82/AC16.27.2 desktop stage 1 review keeps transaction table readable at 1440px", async ({ page }) => {
    await gotoReady(page, "/statements/stmt-mobile/review");

    const desktopRegion = page.getByTestId("stage1-desktop-transaction-region");
    await expect(desktopRegion).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
    await expect(desktopRegion.getByText("Long mobile grocery transaction from a bank statement")).toBeVisible();
    await expectNoLocalHorizontalScroll(page, "stage1-desktop-transaction-region");
    await expectNoDocumentHorizontalScroll(page);
  });

  test("AC8.13.82/AC16.27.3 desktop stage 2 review keeps pending matches readable at 1440px", async ({ page }) => {
    await gotoReady(page, "/reconciliation/review-queue");

    const desktopRegion = page.getByTestId("stage2-desktop-match-region");
    await expect(desktopRegion).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
    await expect(desktopRegion.getByText("Long reconciliation match needing mobile approval")).toBeVisible();
    await expectNoLocalHorizontalScroll(page, "stage2-desktop-match-region");
    await expectNoDocumentHorizontalScroll(page);
  });
});

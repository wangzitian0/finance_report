import { expect, test, type Page } from "@playwright/test";

const COLD_ROUTE_TIMEOUT_MS = 10_000;
const MIN_SCREENSHOT_BYTES = 10_000;

const visualAccounts = {
  items: [
    {
      id: "cash-visual",
      name: "Operating Cash",
      code: "1010",
      type: "ASSET",
      currency: "SGD",
      balance: "12500.00",
      is_active: true,
      description: "Primary account for visual smoke coverage",
    },
    {
      id: "revenue-visual",
      name: "Consulting Revenue",
      code: "4010",
      type: "INCOME",
      currency: "SGD",
      balance: "0.00",
      is_active: true,
      description: "Income account",
    },
  ],
  total: 2,
};

const visualStatements = {
  items: [
    {
      id: "stmt-visual",
      original_filename: "visual-smoke-statement-june-2026.pdf",
      institution: "Visual Bank",
      account_last4: "6789",
      currency: "SGD",
      period_start: "2026-06-01",
      period_end: "2026-06-30",
      opening_balance: "1000.00",
      closing_balance: "1123.45",
      confidence_score: 94,
      balance_validated: true,
      status: "parsed",
      validation_error: null,
      transactions: [
        {
          id: "txn-visual-1",
          amount: "123.45",
          description: "Visual smoke transaction",
        },
      ],
    },
  ],
  total: 1,
};

const visualStatementReview = {
  id: "stmt-visual",
  account_id: "cash-visual",
  original_filename: "visual-smoke-statement-june-2026.pdf",
  institution: "Visual Bank",
  account_last4: "6789",
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
      id: "txn-visual-1",
      txn_date: "2026-06-05",
      description: "Visual smoke transaction",
      amount: "123.45",
      direction: "OUT",
      currency: "SGD",
      confidence: "high",
      confidence_tier: "high",
    },
  ],
};

async function installVisualApiMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("finance_access_token", "visual-smoke-token");
    localStorage.setItem("finance_user_id", "visual-user");
    localStorage.setItem("finance_user_email", "visual@example.com");
  });

  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};

    if (path === "/api/accounts") {
      body = visualAccounts;
    } else if (path === "/api/accounts/processing/summary") {
      body = {
        pending_count: 0,
        pending_total: "0.00",
        current_balance: "0.00",
        currency: "SGD",
        oldest_pending_date: null,
      };
    } else if (path === "/api/statements") {
      body = visualStatements;
    } else if (path === "/api/statements/pending-review") {
      body = { items: [{ id: "stmt-visual" }], total: 1 };
    } else if (path === "/api/statements/stmt-visual/review") {
      body = visualStatementReview;
    } else if (path === "/api/statements/stage2/queue") {
      body = { pending_matches: [], consistency_checks: [], has_unresolved_checks: false };
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
}

async function gotoReady(page: Page, path: string) {
  await page.goto(path, { waitUntil: "networkidle" });
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

async function expectNonblankScreenshot(page: Page) {
  const screenshot = await page.screenshot({ fullPage: true });
  expect(screenshot.byteLength).toBeGreaterThan(MIN_SCREENSHOT_BYTES);
}

async function expectAppShellVisible(page: Page, mobile: boolean) {
  if (mobile) {
    await expect(page.getByLabel("Open navigation menu")).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
    return;
  }

  await expect(page.getByRole("navigation", { name: "Sidebar navigation" })).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
  await expect(page.getByRole("navigation", { name: "Open workspace tabs" })).toBeVisible();
}

async function expectVisualSmokePage(page: Page, path: string, heading: string, mobile: boolean) {
  await gotoReady(page, path);
  await expectAppShellVisible(page, mobile);
  await expect(page.getByRole("heading", { name: heading })).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
  await expectNoDocumentHorizontalScroll(page);
  await expectNonblankScreenshot(page);
}

test.describe("AC16.30.5 desktop visual smoke", () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test.beforeEach(async ({ page }) => {
    await installVisualApiMocks(page);
  });

  test("captures representative app-shell, accounts, statements, and review pages", async ({ page }) => {
    await expectVisualSmokePage(page, "/accounts", "Accounts", false);
    await expect(page.getByText("Operating Cash")).toBeVisible();

    await expectVisualSmokePage(page, "/statements", "Bank Statements", false);
    await expect(page.getByText("visual-smoke-statement-june-2026.pdf")).toBeVisible();

    await expectVisualSmokePage(page, "/statements/stmt-visual/review", "visual-smoke-statement-june-2026.pdf", false);
    await expect(page.getByTestId("stage1-desktop-transaction-region").getByText("Visual smoke transaction")).toBeVisible();
  });
});

test.describe("AC16.30.5 mobile visual smoke", () => {
  test.use({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
  });

  test.beforeEach(async ({ page }) => {
    await installVisualApiMocks(page);
  });

  test("captures representative app-shell, accounts, statements, and review pages", async ({ page }) => {
    await expectVisualSmokePage(page, "/accounts", "Accounts", true);
    await expect(page.getByText("Operating Cash")).toBeVisible();

    await expectVisualSmokePage(page, "/statements", "Bank Statements", true);
    await expect(page.getByText("visual-smoke-statement-june-2026.pdf")).toBeVisible();

    await expectVisualSmokePage(page, "/statements/stmt-visual/review", "visual-smoke-statement-june-2026.pdf", true);
    await expect(page.getByTestId("stage1-mobile-transaction-card-txn-visual-1").getByText("Visual smoke transaction")).toBeVisible();
  });
});

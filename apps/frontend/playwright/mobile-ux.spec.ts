import { expect, test, type Page } from "@playwright/test";

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

async function installMobileApiMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("finance_access_token", "mobile-review-token");
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
      body = { items: [], total: 0 };
    } else if (path === "/api/statements/stage2/queue") {
      body = { pending_matches: [] };
    } else if (path === "/api/accounts/processing/summary") {
      body = { current_balance: "0.00", pending_total: "0.00" };
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

test("AC16.25.1 mobile review routes avoid document horizontal scrolling", async ({ page }) => {
  await gotoReady(page, "/review/ai-suggestions");
  await expect(page.getByTestId("ai-suggestions-mobile-list")).toBeVisible();
  await expectNoDocumentHorizontalScroll(page);
  await page.getByLabel("Open navigation menu").click();
  await expect(page.getByRole("dialog", { name: "Finance Report" })).toBeVisible();
  await expectNoDocumentHorizontalScroll(page);
  await page.getByRole("button", { name: "Close panel" }).click();

  await gotoReady(page, "/journal");
  await page.getByText("Mobile review sample entry").click();
  await expect(page.getByTestId("journal-lines-mobile")).toBeVisible();
  await expectNoDocumentHorizontalScroll(page);
});

test("AC16.25.2 AI suggestions mobile cards expose feedback actions", async ({ page }) => {
  await gotoReady(page, "/review/ai-suggestions");

  const card = page.getByTestId("ai-suggestion-mobile-card-suggestion-mobile");
  await expect(card).toBeVisible();
  await expect(card.getByText("Long mobile transaction description")).toBeVisible();
  await expect(card.getByLabel("Corrected value")).toBeVisible();
  await expect(card.getByRole("button", { name: "Accept", exact: true })).toBeVisible();
  await expect(card.getByRole("button", { name: "Reject", exact: true })).toBeVisible();
  await expect(card.getByRole("button", { name: "Edit-then-Accept", exact: true })).toBeVisible();
  await expectNoDocumentHorizontalScroll(page);
});

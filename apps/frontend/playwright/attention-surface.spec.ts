import { expect, test, type Page } from "@playwright/test";

const COLD_ROUTE_TIMEOUT_MS = 10_000;

// EPIC-022 AC22.6.4 / AC22.11.3: desktop + mobile smoke for the
// confidence-ranked attention queue, attention-origin action links, and the Home
// trust meter, without layout overflow.
async function installAttentionMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("finance_user_id", "attention-smoke-user");
    localStorage.setItem("finance_user_email", "attention-smoke@example.com");
  });

  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};

    if (path === "/api/statements") {
      body = {
        total: 1,
        items: [
          {
            id: "stmt-1",
            user_id: "attention-smoke-user",
            file_path: "/x",
            original_filename: "march-statement.pdf",
            institution: "DBS",
            status: "parsed",
            confidence_score: 72,
            balance_validated: false,
            created_at: "2026-03-01",
            updated_at: "2026-03-01",
            transactions: [],
          },
        ],
      };
    } else if (path === "/api/reconciliation/stats") {
      body = {
        total_transactions: 50,
        matched_transactions: 40,
        unmatched_transactions: 4,
        pending_review: 2,
        auto_accepted: 38,
        match_rate: 80,
        score_distribution: {},
      };
    } else if (path === "/api/accounts/processing/pending") {
      body = { total: 0, items: [] };
    } else if (path === "/api/reconciliation/unmatched") {
      body = { items: [], total: 0 };
    }

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

test.describe("AC22.6.4 attention surface smoke", () => {
  test.beforeEach(async ({ page }) => {
    await installAttentionMocks(page);
  });

  for (const { label, width, height } of [
    { label: "desktop", width: 1440, height: 1000 },
    { label: "mobile", width: 390, height: 844 },
  ]) {
    test(`${label} renders the attention queue ranked by confidence without overflow`, async ({ page }) => {
      await page.setViewportSize({ width, height });

      await page.goto("/attention", { waitUntil: "networkidle" });

      await expect(page.getByRole("heading", { name: "Needs your attention" })).toBeVisible({
        timeout: COLD_ROUTE_TIMEOUT_MS,
      });
      // Both the reconciliation and statement-review sources render as rows
      // (confidence-ordering itself is covered by attention.test.ts unit tests).
      await expect(page.getByText(/unmatched transaction/i)).toBeVisible();
      await expect(page.getByText("march-statement.pdf")).toBeVisible();
      // Each row deep-links to its action surface and preserves the attention origin.
      await expect(page.locator('a[href="/statements/stmt-1/review?from=attention"]')).toBeVisible();
      await expect(page.locator('a[href="/reconciliation/unmatched?from=attention"]')).toBeVisible();

      await expectNoDocumentHorizontalScroll(page);
    });

    test(`${label} surfaces the Home trust meter linking to the attention queue`, async ({ page }) => {
      await page.setViewportSize({ width, height });

      await page.goto("/", { waitUntil: "networkidle" });

      const trustMeter = page.getByRole("link", { name: "Items that need your attention" });
      await expect(trustMeter).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
      await expect(trustMeter).toHaveAttribute("href", "/attention");

      await expectNoDocumentHorizontalScroll(page);
    });
  }
});

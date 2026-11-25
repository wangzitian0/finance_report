import { expect, type Locator, type Page } from "@playwright/test";

type RecordPayload = Record<string, unknown>;
type Scope = Page | Locator;

export const T = 10_000;

export const tid = (scope: Scope, id: string) => scope.getByTestId(id);

export const hdg = (scope: Scope, name: string | RegExp, exact = true) =>
  scope.getByRole("heading", typeof name === "string" ? { name, exact } : { name });

export const vis = (locator: Locator, timeout = T) => expect(locator).toBeVisible({ timeout });

export async function installApiMocks(
  page: Page,
  userId: string,
  routeMap: RecordPayload | ((path: string) => unknown),
  fallback: unknown = {},
) {
  await page.addInitScript(
    ([id, email]) => {
      localStorage.setItem("finance_user_id", id);
      localStorage.setItem("finance_user_email", email);
    },
    [userId, `${userId}@example.com`],
  );
  await page.route("**/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    let body = fallback;
    if (typeof routeMap === "function") {
      body = routeMap(pathname);
    } else if (pathname in routeMap) {
      body = routeMap[pathname];
    } else {
      for (const [pattern, value] of Object.entries(routeMap)) {
        if (pattern.endsWith("*") && pathname.startsWith(pattern.slice(0, -1))) {
          body = value;
          break;
        }
      }
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

export async function gotoReady(page: Page, path: string, viewport?: { width: number; height: number }) {
  if (viewport) {
    await page.setViewportSize(viewport);
  }
  await page.goto(path, { waitUntil: "networkidle" });
}

export async function noHScroll(page: Page, checkX = true) {
  const metrics = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    scrollX: window.scrollX,
  }));
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth);
  if (checkX) {
    expect(metrics.scrollX).toBe(0);
  }
}

export const transfersSummary = () => ({
  pending_count: 0,
  pending_total: "0.00",
  current_balance: "0.00",
  currency: "SGD",
  oldest_pending_date: null,
});

export const reviewQueue = (overrides: RecordPayload = {}) => ({
  pending_matches: [],
  consistency_checks: [],
  has_unresolved_checks: false,
  ...overrides,
});

export const stmtFixture = (id: string, overrides: RecordPayload = {}) => ({
  id,
  user_id: "u",
  account_id: "a1",
  original_filename: `${id}.csv`,
  institution: "DBS",
  currency: "SGD",
  period_start: "2026-06-01",
  period_end: "2026-06-30",
  opening_balance: "1000.00",
  closing_balance: "1123.45",
  status: "parsed",
  stage1_status: "pending_review",
  confidence_score: 98,
  balance_validated: true,
  transactions: [],
  ...overrides,
});

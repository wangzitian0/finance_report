import { expect, test, type Page } from "@playwright/test";

// #2646: the front door to the items that need the user. The data is the data of the LE review on
// staging v0.2.29: statements from July to October, one unmatched row "PayNow Transfer REF 4471", a
// brokerage file at 20 % confidence and the October statement at 80 %. The workflow status reports
// the false period blocker of the old 1Y window, so the queue must lead without it.

const COLD_ROUTE_TIMEOUT_MS = 10_000;
const VIEWPORTS = [
  { label: "mobile", width: 375, height: 812 },
  { label: "desktop", width: 1280, height: 800 },
] as const;

const approved = (id: string, periodStart: string, periodEnd: string) => ({
  id,
  original_filename: `${id}.csv`,
  institution: "DBS",
  status: "approved",
  confidence_score: 98,
  balance_validated: true,
  period_start: periodStart,
  period_end: periodEnd,
  created_at: `${periodEnd}T00:00:00Z`,
  updated_at: `${periodEnd}T00:00:00Z`,
  transactions: [],
});

const STATEMENTS = [
  approved("dbs-2026-07", "2026-07-01", "2026-07-31"),
  approved("dbs-2026-08", "2026-08-01", "2026-08-31"),
  approved("dbs-2026-09", "2026-09-01", "2026-09-30"),
  {
    ...approved("dbs-2026-10", "2026-10-01", "2026-10-31"),
    original_filename: "dbs-2026-10.csv",
    status: "parsed",
    confidence_score: 80,
  },
  {
    ...approved("ibkr-positions", "2026-10-01", "2026-10-31"),
    original_filename: "ibkr-positions.csv",
    status: "parsed",
    confidence_score: 20,
  },
];

const HEALTH_A = {
  score: 99,
  grade: "A_AUDIT_READY",
  as_of_date: "2026-10-22",
  currency: "SGD",
  equation_invariant: { is_healthy: true, name: "Equation", summary: "Balanced", detail: "", delta: "0" },
  temporal_continuity_invariant: { is_healthy: true, name: "Continuity", summary: "Continuous", detail: "", delta: "0" },
  reconciliation_purity_invariant: { is_healthy: true, name: "Purity", summary: "Pure", detail: "", delta: "0" },
  lineage_anchors_invariant: { is_healthy: true, name: "Lineage", summary: "Traced", detail: "", delta: "0" },
  timeline: [],
  action_items: [],
};

async function installMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("finance_user_id", "needs-you-user");
    localStorage.setItem("finance_user_email", "needs-you@example.com");
  });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = { items: [], total: 0 };
    if (path === "/api/statements") body = { items: STATEMENTS, total: STATEMENTS.length };
    else if (path === "/api/reconciliation/stats") {
      body = {
        total_transactions: 26,
        matched_transactions: 25,
        unmatched_transactions: 1,
        pending_review: 0,
        auto_accepted: 25,
        match_rate: 96,
        score_distribution: {},
      };
    } else if (path === "/api/reconciliation/unmatched") {
      body = {
        items: [{ id: "txn-paynow", txn_date: "2026-10-14", description: "PayNow Transfer REF 4471", amount: "250.00", direction: "OUT", currency: "SGD" }],
        total: 1,
      };
    } else if (path === "/api/workflow/status") {
      body = {
        primary_state: "blocked",
        next_action: { type: "resolve_blocker", count: 1, href: "/reports?tab=package", label: "Resolve the blocking condition", summary: "" },
        report_readiness: { state: "blocked", blocking_count: 1, href: "/reports?tab=package" },
        event_counts: { unread: 0, action_required: 0, blocked: 1 },
      };
    } else if (path === "/api/reports/data-quality") body = HEALTH_A;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

/** The top of the fixed mobile tab bar, or the viewport height when no tab bar shows. */
async function visibleBottom(page: Page, height: number): Promise<number> {
  const bar = page.getByRole("navigation", { name: "Primary" });
  if (!(await bar.isVisible())) return height;
  const box = await bar.boundingBox();
  return box ? Math.min(box.y, height) : height;
}

test.describe("#2646 the front door to the items that need the user", () => {
  test.beforeEach(async ({ page }) => {
    await installMocks(page);
  });

  for (const { label, width, height } of VIEWPORTS) {
    // AC-meta.fe-audit-queue.5
    test(`AC-meta.fe-audit-queue.5 /audit shows the Needs Confirmation list in the first viewport (${label})`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await page.goto("/audit", { waitUntil: "networkidle" });

      const queue = page.getByTestId("needs-confirmation-queue");
      const firstRow = queue.getByRole("link", { name: /PayNow Transfer REF 4471/ });
      await expect(firstRow).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });

      // The page is not scrolled: the boxes are in the first viewport.
      const heading = await queue.getByRole("heading", { name: "Needs Confirmation" }).boundingBox();
      const row = await firstRow.boundingBox();
      const bottom = await visibleBottom(page, height);
      expect(heading, "Needs Confirmation heading box").not.toBeNull();
      expect(row, "first queue row box").not.toBeNull();
      expect(heading!.y, "heading top in px").toBeGreaterThanOrEqual(0);
      expect(row!.y + row!.height, `first row bottom in px (visible bottom ${bottom})`).toBeLessThanOrEqual(bottom);
      await expect(page.getByRole("tab", { name: /Needs you/ })).toHaveAttribute("aria-selected", "true");
    });

    test(`AC-reporting.fe-period-cockpit.9 Home names the count and the first item above the statement cards (${label})`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await page.goto("/", { waitUntil: "networkidle" });

      const banner = page.getByRole("region", { name: "Needs attention" });
      await expect(banner.getByRole("heading", { name: "3 items need you" })).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
      await expect(banner.getByRole("link", { name: "PayNow Transfer REF 4471" })).toHaveAttribute(
        "href",
        "/reconciliation?tab=unmatched&from=attention",
      );
      await expect(page.getByText("A blocker holds your reports")).toHaveCount(0);

      const bannerBox = await banner.boundingBox();
      const cardsBox = await page.getByRole("region", { name: "Three-statement cockpit" }).boundingBox();
      expect(bannerBox, "banner box").not.toBeNull();
      expect(cardsBox, "cockpit box").not.toBeNull();
      expect(bannerBox!.y + bannerBox!.height, "banner bottom above the cockpit top").toBeLessThanOrEqual(cardsBox!.y);
    });
  }

  test("AC-meta.fe-audit-queue.4 the Health tab holds the audit-ready grade while a row is unmatched", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/audit?tab=health", { waitUntil: "networkidle" });

    await expect(page.getByText("Open items remain", { exact: true })).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
    await expect(page.getByText(/Audit[- ]Ready/i)).toHaveCount(0);
  });

  test("AC-reconciliation.fe-tabs.2 /reconciliation opens on Unmatched when a row is unmatched", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/reconciliation", { waitUntil: "networkidle" });

    const tabs = page.getByRole("navigation", { name: "Reconciliation workspace views" });
    await expect(tabs.getByRole("link", { name: /Unmatched/ })).toHaveAttribute("aria-current", "page", {
      timeout: COLD_ROUTE_TIMEOUT_MS,
    });
    await expect(tabs.getByRole("link", { name: "Matches" })).toHaveAttribute("href", "/reconciliation?tab=matches");
  });
});

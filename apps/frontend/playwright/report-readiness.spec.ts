import { expect, test, type Page } from "@playwright/test";

const COLD_ROUTE_TIMEOUT_MS = 10_000;

async function installReportReadinessMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("finance_access_token", "report-readiness-token");
    localStorage.setItem("finance_user_id", "report-readiness-user");
    localStorage.setItem("finance_user_email", "report-readiness@example.com");
  });

  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};

    if (path === "/api/workflow/status") {
      body = {
        primary_state: "blocked",
        next_action: { type: "resolve_blocker", count: 1, href: "/accounts/processing" },
        report_readiness: { state: "blocked", blocking_count: 1, href: "/reports/package" },
        event_counts: { unread: 1, action_required: 0, blocked: 1 },
      };
    } else if (path === "/api/reports/package/contract") {
      body = {
        package_id: "personal-financial-report-package",
        version: "1.0",
        period_semantics: {},
        export_contract: { formats: ["json"], csv_columns: [] },
        sections: [
          {
            section_id: "balance_sheet",
            label: "Balance Sheet",
            owner_epic: "EPIC-005",
            source_endpoint: "/api/reports/balance-sheet",
            status: "ready",
          },
        ],
      };
    } else if (path === "/api/reports/package/readiness") {
      body = {
        package_id: "personal-financial-report-package",
        state: "blocked",
        label: "Blocked",
        action_href: "/accounts/processing",
        blocking_count: 1,
        blockers: [
          {
            code: "processing_account_unresolved",
            label: "Processing account unresolved",
            severity: "blocking",
            count: 1,
            reason: "Processing account balance cannot be converted to SGD: No FX rate available for USD/SGD.",
            action_href: "/accounts/processing",
          },
        ],
        source_summary: { statements: 2, posted_journal_entries: 3, manual_valuations: 1 },
      };
    } else if (path === "/api/reports/package/annualized-income-schedule") {
      body = {
        section_id: "annualized_income_long_term",
        trailing_period_days: 365,
        income: {
          annualized_salary: "0.00",
          annualized_bonus: "0.00",
          annualized_dividend: "0.00",
          annualized_total: "0.00",
          currency: "SGD",
        },
        restricted_holdings: [],
        net_worth_treatment: {
          liquid_net_worth_default: "exclude_restricted",
          restricted_wealth_basis: "disclose_separately",
        },
        notes: ["Readiness smoke fixture."],
      };
    } else if (path === "/api/reports/package/notes") {
      body = {
        section_id: "notes",
        label: "Notes",
        status: "ready",
        notes: [],
        non_compliance_statement: "Not professional advice.",
      };
    } else if (path === "/api/reports/package/traceability") {
      body = {
        section_id: "traceability_appendix",
        label: "Traceability Appendix",
        status: "ready",
        lines: [],
        completeness_warnings: [],
      };
    }

    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
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

test.describe("AC19.7.7 AC19.7.8 report readiness smoke", () => {
  for (const scenario of [
    { name: "desktop", viewport: { width: 1440, height: 1000 } },
    { name: "mobile", viewport: { width: 390, height: 844 } },
  ]) {
    test(`${scenario.name} renders report readiness blockers before package output`, async ({ page }) => {
      await page.setViewportSize(scenario.viewport);
      await installReportReadinessMocks(page);

      await page.goto("/reports/package", { waitUntil: "domcontentloaded" });

      await expect(page.getByRole("heading", { name: "Report Readiness" })).toBeVisible({
        timeout: COLD_ROUTE_TIMEOUT_MS,
      });
      await expect(page.getByText("processing_account_unresolved")).toBeVisible();
      await expect(page.getByRole("link", { name: "Blocked" })).toHaveAttribute("href", "/accounts/processing");
      await expect(page.getByRole("heading", { name: "Balance Sheet" })).toBeVisible();
      await expectNoDocumentHorizontalScroll(page);
    });
  }
});

import { expect, test, type Page } from "@playwright/test";

import type { PersonalReportPackageDocument } from "../src/lib/types";

const COLD_ROUTE_TIMEOUT_MS = 10_000;

const packageDocument = {
  schema_version: "2",
  lifecycle: "preview",
  snapshot_id: null,
  package_decision_id: null,
  generated_at: "2026-05-20T12:00:00Z",
  frozen_at: null,
  package_id: "personal-financial-report-package",
  status: "draft",
  context: {
    framework_id: "personal_us_gaap_like",
    start_date: "2025-05-20",
    end_date: "2026-05-20",
    as_of_date: "2026-05-20",
    currency: "SGD",
  },
  contract: {
    package_id: "personal-financial-report-package",
    version: "2.0",
    period_semantics: {},
    supported_frameworks: ["personal_us_gaap_like", "personal_hkfrs_like"],
    selected_framework_id: "personal_us_gaap_like",
    export_contract: { formats: ["json", "csv"], csv_columns: [] },
    sections: [
      {
        section_id: "balance_sheet",
        label: "Balance Sheet",
        owner_epic: "EPIC-005",
        period_type: "as_of",
        required: true,
        status: "ready",
      },
    ],
  },
  readiness: {
    package_id: "personal-financial-report-package",
    state: "blocked",
    label: "Blocked",
    action_href: "/accounts/processing",
    blocking_count: 1,
    input_coverage: {
      manifest_decision_count: 0,
      authoritative_input_count: 0,
      unproven_input_count: 1,
    },
    blockers: [
      {
        code: "processing_account_unresolved",
        label: "Processing account unresolved",
        severity: "blocking",
        count: 1,
        reason:
          "Processing account balance cannot be converted to SGD: No FX rate available for USD/SGD.",
        action_href: "/accounts/processing",
      },
    ],
  },
  framework_policy: {
    result_id: "policy-result:personal_us_gaap_like:smoke",
    framework_id: "personal_us_gaap_like",
    matrix_version: "2.0",
    report_period_start: "2025-05-20",
    report_period_end: "2026-05-20",
    generated_at: "2026-05-20",
    required_statements: ["balance_sheet", "notes", "traceability_appendix"],
    decisions: [],
    gaps: [],
  },
  input_manifest: [],
  sections: {
    balance_sheet: {
      as_of_date: "2026-05-20",
      currency: "SGD",
      assets: [],
      liabilities: [],
      equity: [],
      total_assets: "0.00",
      total_liabilities: "0.00",
      total_equity: "0.00",
      net_income: "0.00",
      unrealized_fx_gain_loss: "0.00",
      net_worth_adjustment_gain_loss: "0.00",
      fx_warnings: [],
      portfolio_warnings: [],
      opening_balance_warnings: [],
      equation_delta: "0.00",
      is_balanced: true,
    },
    income_statement: {
      start_date: "2025-05-20",
      end_date: "2026-05-20",
      currency: "SGD",
      income: [],
      expenses: [],
      total_income: "0.00",
      total_expenses: "0.00",
      net_income: "0.00",
      fx_warnings: [],
      trends: [],
    },
    cash_flow: {
      start_date: "2025-05-20",
      end_date: "2026-05-20",
      currency: "SGD",
      operating: [],
      investing: [],
      financing: [],
      summary: {
        operating_activities: "0.00",
        investing_activities: "0.00",
        financing_activities: "0.00",
        net_cash_flow: "0.00",
        beginning_cash: "0.00",
        ending_cash: "0.00",
      },
      fx_warnings: [],
      proof_state: "unproven",
      proof_reasons: ["cash_identity_missing"],
    },
    investment_performance: {
      period_start: "2025-05-20",
      period_end: "2026-05-20",
      as_of_date: "2026-05-20",
      currency: "SGD",
      holdings: [],
      xirr: null,
      time_weighted_return: null,
      money_weighted_return: null,
      realized_pnl: "0.00",
      unrealized_pnl: "0.00",
      dividend_income: "0.00",
      dividend_yield: null,
      allocation: [],
      data_freshness: {
        stale: false,
        latest_price_date: null,
        market_data_provider: null,
        stale_holdings: [],
      },
      source_links: [],
      notes: [],
    },
    annualized_income_long_term: {
      section_id: "annualized_income_long_term",
      label: "Annualized Income & Long-Term Compensation",
      as_of_date: "2026-05-20",
      trailing_period_start: "2025-05-20",
      trailing_period_end: "2026-05-20",
      trailing_period_days: 365,
      income: {
        annualized_salary: "0.00",
        annualized_bonus: "0.00",
        annualized_dividend: "0.00",
        annualized_total: "0.00",
        currency: "SGD",
        calculation_basis: "smoke",
      },
      restricted_holdings: [],
      restricted_fair_value_total: "0.00",
      restricted_fair_value_total_currency: "SGD",
      net_worth_treatment: {
        liquid_net_worth_default: "exclude_restricted",
        restricted_wealth_basis: "disclose_separately",
        exclude_restricted_query: "/reports/net-worth?include_restricted=false",
        include_restricted_query: "/reports/net-worth?include_restricted=true",
      },
      notes: [],
    },
    notes: {
      section_id: "notes",
      label: "Notes & Disclosures",
      status: "ready",
      non_compliance_statement: "Not professional advice.",
      notes: [],
    },
    traceability_appendix: {
      section_id: "traceability_appendix",
      label: "Traceability Appendix",
      status: "ready",
      lines: [],
      completeness_warnings: [],
    },
  },
} satisfies PersonalReportPackageDocument;

async function installReportReadinessMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("finance_user_id", "report-readiness-user");
    localStorage.setItem("finance_user_email", "report-readiness@example.com");
  });

  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};

    if (path === "/api/workflow/status") {
      body = {
        primary_state: "blocked",
        next_action: {
          type: "resolve_blocker",
          count: 1,
          href: "/accounts/processing",
        },
        report_readiness: {
          state: "blocked",
          blocking_count: 1,
          href: "/reports/package",
        },
        event_counts: { unread: 1, action_required: 0, blocked: 1 },
      };
    } else if (path === "/api/reports/package/snapshots") {
      body = [];
    } else if (path === "/api/reports/package") {
      body = packageDocument;
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

test.describe("AC19.8.7 AC19.8.8 AC22.8.4 AC22.19 report package smoke", () => {
  for (const scenario of [
    { name: "desktop", viewport: { width: 1440, height: 1000 } },
    { name: "mobile", viewport: { width: 390, height: 844 } },
  ]) {
    // AC-reporting.fe-ia-reports.17
    // AC-reporting.fe-remainder-reports.13
    test(`${scenario.name} renders cover, contents, and readiness before package output`, async ({
      page,
    }) => {
      await page.setViewportSize(scenario.viewport);
      await installReportReadinessMocks(page);

      await page.goto("/reports/package", { waitUntil: "domcontentloaded" });
      await page.getByRole("button", { name: "US-like" }).click();

      await expect(
        page.getByRole("heading", { name: "Report Readiness" }),
      ).toBeVisible({
        timeout: COLD_ROUTE_TIMEOUT_MS,
      });
      const cover = page.getByRole("region", { name: "Report package cover" });
      await expect(cover.getByText("personal-financial-report-package")).toBeVisible();
      await expect(cover.getByText("US-like")).toBeVisible();

      const tableOfContents = page.getByRole("navigation", {
        name: "Report package table of contents",
      });
      await expect(
        tableOfContents.getByRole("link", { name: "Report Readiness" }),
      ).toHaveAttribute("href", "#package-readiness");
      await expect(
        tableOfContents.getByRole("link", { name: "Balance Sheet" }),
      ).toHaveAttribute("href", "#package-section-balance_sheet");

      const readinessSection = page.locator("#package-readiness");
      await expect(
        readinessSection.getByText("Processing account unresolved"),
      ).toBeVisible();
      await expect(
        readinessSection.getByText(
          "Processing account balance cannot be converted to SGD: No FX rate available for USD/SGD.",
        ),
      ).toBeVisible();
      await expect(page.getByRole("link", { name: "Blocked" })).toHaveAttribute(
        "href",
        "/accounts/processing",
      );

      const readinessAuditDetails = readinessSection.locator("details", {
        hasText: "Readiness audit details",
      });
      const rawBlockerCode = readinessAuditDetails.getByText(
        "processing_account_unresolved",
      );
      await expect(readinessAuditDetails).not.toHaveAttribute("open", "");
      // Each blocker code is shown once as the audit card heading and once as
      // its labelled value; both must stay behind the collapsed disclosure.
      await expect(rawBlockerCode).toHaveCount(2);
      await expect(rawBlockerCode.first()).toBeHidden();
      await readinessAuditDetails.getByText("Readiness audit details").click();
      await expect(rawBlockerCode.first()).toBeVisible();

      await expect(
        page.getByRole("heading", { name: "Balance Sheet" }),
      ).toBeVisible();
      await expectNoDocumentHorizontalScroll(page);
    });
  }
});

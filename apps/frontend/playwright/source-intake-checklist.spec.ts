import { expect, test, type Locator, type Page } from "@playwright/test";

const COLD_ROUTE_TIMEOUT_MS = 10_000;

const sourceIntakeCards = [
  { id: "bank_statement", label: "Bank statements", href: "/upload" },
  { id: "brokerage_statement", label: "Brokerage statements", href: "/upload" },
  { id: "settlement_note", label: "Settlement notes", href: "/upload" },
  {
    id: "esop_rsu_plan",
    label: "ESOP / RSU plans",
    href: "/portfolio/evidence?source_class=esop_rsu_plan",
  },
  {
    id: "property_statement",
    label: "Property statements",
    href: "/portfolio/evidence?source_class=property_statement",
  },
  {
    id: "liability_statement",
    label: "Liability statements",
    href: "/portfolio/evidence?source_class=liability_statement",
  },
  { id: "csv_export", label: "CSV exports", href: "/upload" },
  { id: "manual_record", label: "Manual records", href: "/journal" },
] as const;

const sourceTrustSummary = {
  source_classes: sourceIntakeCards.map((card) => card.id),
  deterministic_pr_source_classes: [
    "bank_statement",
    "brokerage_statement",
    "settlement_note",
    "csv_export",
  ],
  post_merge_llm_ocr_source_classes: ["bank_statement", "brokerage_statement"],
  manual_trusted_source_classes: [
    "esop_rsu_plan",
    "property_statement",
    "liability_statement",
  ],
  gap_source_classes: ["manual_record"],
  blocker_codes: ["missing_source_coverage"],
};

async function installSourceIntakeMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("finance_user_id", "source-intake-user");
    localStorage.setItem("finance_user_email", "source-intake@example.com");
  });

  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};

    if (path === "/api/statements") {
      body = { items: [], total: 0 };
    } else if (path === "/api/reports/package/readiness") {
      body = {
        package_id: "personal-financial-report-package",
        state: "blocked",
        label: "Blocked",
        action_href: "/upload",
        blocking_count: 1,
        blockers: [
          {
            code: "missing_source_coverage",
            label: "Manual record source coverage missing",
            severity: "blocking",
            count: 1,
            reason: "Manual records still need trusted source evidence.",
            action_href: "/journal",
          },
        ],
        source_summary: {
          statements: 0,
          posted_journal_entries: 0,
          manual_valuations: 0,
        },
        source_trust_summary: sourceTrustSummary,
      };
    } else if (path === "/api/llm/catalog") {
      body = {
        models: [
          {
            id: "qwen/qwen-2.5-vl-7b-instruct:free",
            provider_id: "openrouter-env",
            is_free: true,
            modalities: ["image"],
            supports_reasoning: false,
          },
        ],
      };
    } else if (path === "/api/workflow/status") {
      body = {
        primary_state: "needs_action",
        next_action: {
          type: "upload",
          count: 1,
          href: "/upload",
          label: "Upload source",
          summary: "Upload source evidence before reading reports.",
        },
        report_readiness: {
          state: "blocked",
          blocking_count: 1,
          href: "/upload",
        },
        event_counts: { unread: 0, action_required: 1, blocked: 1 },
      };
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

async function expectChecklistLinksNotClipped(checklist: Locator) {
  const clippedLabels = await checklist.locator("a").evaluateAll((links) =>
    links
      .filter((link) => (
        link.scrollWidth > link.clientWidth
        || link.scrollHeight > link.clientHeight
      ))
      .map((link) => link.textContent?.trim() ?? ""),
  );

  expect(clippedLabels).toEqual([]);
}

test.describe("AC19.15.1 AC19.15.2 source intake checklist upload smoke", () => {
  for (const scenario of [
    { name: "desktop", viewport: { width: 1440, height: 1000 } },
    { name: "mobile", viewport: { width: 390, height: 844 } },
  ]) {
    test(`${scenario.name} renders every source class with usable intake paths`, async ({
      page,
    }) => {
      await page.setViewportSize(scenario.viewport);
      await installSourceIntakeMocks(page);

      await page.goto("/upload", { waitUntil: "networkidle" });

      const checklist = page.getByRole("region", {
        name: "Report source intake checklist",
      });
      await expect(checklist).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
      await expect(checklist.getByText("8 source classes")).toBeVisible();

      for (const source of sourceIntakeCards) {
        const card = checklist.getByTestId(`source-intake-${source.id}`);
        await expect(card).toBeVisible();
        await expect(
          card.getByRole("heading", { name: source.label }),
        ).toBeVisible();
        await expect(card.getByText(source.id, { exact: true })).toBeVisible();
        await expect(card.getByRole("link")).toHaveAttribute(
          "href",
          source.href,
        );
      }

      await expect(
        checklist.getByTestId("source-intake-manual_record").getByText("Needs source"),
      ).toBeVisible();
      await expect(
        checklist.getByTestId("source-intake-bank_statement").getByText("Import supported"),
      ).toBeVisible();
      await expect(
        checklist.getByTestId("source-intake-property_statement").getByText("Manual-trusted"),
      ).toBeVisible();

      await expectChecklistLinksNotClipped(checklist);
      await expectNoDocumentHorizontalScroll(page);
    });
  }
});

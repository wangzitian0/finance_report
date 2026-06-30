import { expect, test, type Page } from "@playwright/test";

const COLD_ROUTE_TIMEOUT_MS = 10_000;

async function installMocks(page: Page) {
    await page.addInitScript(() => {
        localStorage.setItem("finance_user_id", "bottom-tab-user");
        localStorage.setItem("finance_user_email", "bottom-tab@example.com");
    });

    await page.route("**/api/**", async (route) => {
        const path = new URL(route.request().url()).pathname;
        let body: unknown = {};

        if (path === "/api/workflow/status") {
            body = {
                primary_state: "idle",
                next_action: null,
                report_readiness: { state: "ready", blocking_count: 0, href: "/reports" },
                event_counts: { unread: 0, action_required: 0, blocked: 0 },
            };
        } else if (path === "/api/workflow/events") {
            body = { items: [], total: 0, sessions: [] };
        } else if (path === "/api/portfolio/holdings") {
            body = { holdings: [] };
        } else if (path.startsWith("/api/journal-entries")) {
            body = { items: [], total: 0 };
        } else if (path === "/api/confidence/north-star") {
            body = { points: [], current: null };
        }

        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
}

async function expectNoHorizontalScroll(page: Page) {
    const metrics = await page.evaluate(() => ({
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
    }));
    expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth);
}

test.describe("AC22.21.7 mobile/PWA bottom-tab IA smoke", () => {
    test.beforeEach(async ({ page }) => {
        await installMocks(page);
        await page.setViewportSize({ width: 390, height: 844 });
    });

    test("the bottom bar opens the Add sheet with both ways to add", async ({ page }) => {
        await page.goto("/", { waitUntil: "networkidle" });

        const bar = page.getByRole("navigation", { name: "Primary" });
        await expect(bar.getByRole("button", { name: "Add" })).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
        await bar.getByRole("button", { name: "Add" }).click();

        const sheet = page.getByRole("dialog", { name: "Add" });
        await expect(sheet.getByText("Upload statement")).toBeVisible();
        await expect(sheet.getByText("Manual entry")).toBeVisible();

        await expectNoHorizontalScroll(page);
    });

    test("the Audit hub aggregates the verify-on-demand machinery", async ({ page }) => {
        await page.goto("/audit", { waitUntil: "networkidle" });

        await expect(page.getByRole("heading", { name: "Audit" })).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
        await expect(page.getByRole("link", { name: /Reconciliation/ })).toHaveAttribute("href", "/reconciliation");
        await expect(page.getByRole("link", { name: /Journal/ })).toHaveAttribute("href", "/journal");
        await expect(page.getByRole("link", { name: /Processing/ })).toHaveAttribute("href", "/processing");

        await expectNoHorizontalScroll(page);
    });

    test("the merged Settings page exposes General/AI/LLM tabs", async ({ page }) => {
        await page.goto("/settings", { waitUntil: "networkidle" });

        await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible({ timeout: COLD_ROUTE_TIMEOUT_MS });
        await expect(page.getByRole("tab", { name: "General" })).toBeVisible();
        await expect(page.getByRole("tab", { name: "AI" })).toBeVisible();
        await expect(page.getByRole("tab", { name: "LLM Models" })).toBeVisible();

        await expectNoHorizontalScroll(page);
    });
});

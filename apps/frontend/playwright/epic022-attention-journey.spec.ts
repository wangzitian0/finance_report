import { test } from "@playwright/test";
import { VP, expectUploadNotice, gotoReady, installApiMocks, noticeRoutes } from "./helpers";

const ID = "11111111-1111-4111-8111-111111111111";
test.describe("AC22.4.5 everyday-user attention journey", () => {
  test.beforeEach(async ({ page }) => installApiMocks(page, "attn-user", noticeRoutes(ID, "Reconciliation blockers", true)));
  for (const { name, width, height } of VP) {
    test(`${name}: both Stage 1 and Stage 2 attention surface in the upload workflow notices with deep links`, async ({ page }) => {
      await gotoReady(page, "/upload", { width, height });
      await expectUploadNotice(page, "Reconciliation blockers", `/statements/${ID}`);
    });
  }
});
// AC-reconciliation.fe-ia-reconciliation.2

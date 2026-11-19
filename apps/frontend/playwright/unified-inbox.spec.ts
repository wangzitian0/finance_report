import { test } from "@playwright/test";
import { VP, expectUploadNotice, gotoReady, installApiMocks, noHScroll, noticeRoutes } from "./helpers";

test.describe("AC22.2.6 unified inbox smoke", () => {
  test.beforeEach(async ({ page }) => installApiMocks(page, "inbox-user", noticeRoutes("stmt-1", "Reconciliation review required")));
  for (const { name, width, height } of VP) {
    test(`${name} surfaces review attention in the upload workflow notices with deep links`, async ({ page }) => {
      await gotoReady(page, "/upload", { width, height });
      await expectUploadNotice(page, "Reconciliation review required", "/statements/stmt-1");
      await noHScroll(page, false);
    });
  }
});
// AC-platform.fe-ia-inbox.3

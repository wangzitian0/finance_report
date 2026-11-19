import { expect, test } from "@playwright/test";
import { T, VP, bs1k, btn, gotoReady, installApiMocks, lineageFixture, txt, vis } from "./helpers";

const AID = "33333333-3333-4333-8333-333333333333", JID = "44444444-4444-4444-8444-444444444444";
const nd = (id: string, node_kind: string, entity_type: string, entity_id: string) => ({ id, node_kind, entity_type, entity_id, properties: {} });
const routes = { "/api/reports/currencies": ["SGD"], "/api/reports/balance-sheet*": bs1k(AID, "Checking"), "/api/reports/account-lineage*": lineageFixture(AID, "Checking", "ASSET", JID, "e1"), "/api/statements/evidence-lineage*": { anchor: null, max_depth: 6, blockers: [], edges: [], nodes: [nd("n1", "ledger_line", "journal_line", JID), nd("n2", "extracted_record", "bank_statement_transaction", "s1"), nd("n3", "atomic_fact", "atomic_transaction", "a1"), nd("n4", "source_document", "uploaded_document", "d1")] } };

test.describe("AC22.4.6 report drill-down to source journey", () => {
  test.beforeEach(({ page }) => installApiMocks(page, "drill", routes));
  for (const { name, width, height } of VP) {
    test(`${name}: a Balance Sheet amount drills to its contributing line and on to the source document`, async ({ page }) => {
      await gotoReady(page, "/reports?tab=balance-sheet", { width, height });
      await btn(page, "View source transactions for Checking").click({ timeout: T });
      await expect(txt(page, "Salary deposit")).toBeVisible();
      await txt(page, "Salary deposit").click();
      await vis(txt(page, "source document"));
    });
  }
});
// AC-reporting.fe-ia-reports.8

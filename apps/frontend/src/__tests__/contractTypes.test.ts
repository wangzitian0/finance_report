import { readdirSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";
import type { Schemas } from "@/lib/api-schema";
import type { AccountListResponse, BankStatementListResponse, JournalEntryListResponse, ListResponse, ManualValuationSnapshotListResponse, ProcessingPendingListResponse, ReconciliationMatchListResponse, UnmatchedTransactionsResponse } from "@/lib/types";
const srcRoot = resolve(__dirname, "..");
const read = (rel: string) => readFileSync(resolve(srcRoot, rel), "utf8");
it("AC25.3.1 AC25.3.2 ListResponse SSOT, OpenAPI keys, alias cleanup, and single fetch boundary", () => {
  const empty = { items: [], total: 0 };
  const acct: AccountListResponse = empty;
  const asEnv: ListResponse<AccountListResponse["items"][number]> = acct;
  const back: AccountListResponse = asEnv;
  const wrappers: ListResponse<unknown>[] = [acct, empty satisfies JournalEntryListResponse, empty satisfies BankStatementListResponse, empty satisfies UnmatchedTransactionsResponse, empty satisfies ReconciliationMatchListResponse, empty satisfies ManualValuationSnapshotListResponse, empty satisfies ProcessingPendingListResponse];
  expect([back.total, wrappers.length]).toEqual([0, 7]);
  const types = read("lib/types.ts");
  expect(types.match(/items:\s*[A-Za-z0-9_]+\[\];\s*\n\s*total:\s*number;/g)).toHaveLength(1);
  expect(types).toContain("export interface ListResponse<T> {");
  for (const x of ["BankStatementTransactionSummary", "ChatMetadata", "PriceUpdateResponse", "PingState =", "export function summarizeTraceabilityAppendix"]) expect(types).not.toContain(x);
  const keys: (Schemas["AccountResponse" | "JournalEntryResponse" | "BalanceSheetResponse" | "IncomeStatementResponse" | "CashFlowResponse" | "BankStatementResponse" | "BankStatementListItemResponse"] | null)[] = Array(7).fill(null);
  expect(keys).toHaveLength(7);
  const files: string[] = [];
  const walk = (p: string) => statSync(p).isDirectory() ? readdirSync(p).forEach((e) => walk(resolve(p, e))) : /\.(ts|tsx)$/.test(p) && !/\.test\.(ts|tsx)$/.test(p) && !p.endsWith("/lib/api.ts") && files.push(p);
  walk(srcRoot);
  const raw = /(?<![A-Za-z0-9_.])fetch\(/;
  expect(files.filter((f) => raw.test(readFileSync(f, "utf8"))).map((f) => f.slice(srcRoot.length + 1))).toEqual([]);
  expect(read("lib/api.ts").match(new RegExp(raw.source, "g")) ?? []).toHaveLength(1);
});
// AC-meta.fe-contract-types.1 AC-meta.fe-contract-types.2

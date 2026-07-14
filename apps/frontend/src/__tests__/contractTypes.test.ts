import { readdirSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";

import { describe, it, expect } from "vitest";

import type { Schemas } from "@/lib/api-schema";
import type {
  AccountListResponse,
  BankStatementListResponse,
  JournalEntryListResponse,
  ListResponse,
  ManagedPositionListResponse,
  ManualValuationSnapshotListResponse,
  ProcessingPendingListResponse,
  ReconciliationMatchListResponse,
  UnmatchedTransactionsResponse,
} from "@/lib/types";

/**
 * EPIC-025 AC25.3: the frontend contract layer derives from single sources of
 * truth instead of re-declaring shapes. These checks are partly compile-time
 * (a drift would fail `tsc`/`npm run build`) and partly source-scans that fail
 * if a duplicate envelope or a second raw-fetch boundary is reintroduced.
 */
describe("frontend contract consolidation (EPIC-025 / #1158)", () => {
  // AC-meta.fe-contract-types.1
  it("AC25.3.1: every list response derives from the single ListResponse<T> envelope", () => {
    // Compile-time: each list response must be mutually assignable with
    // ListResponse<itsItem>. If any wrapper drifts from {items,total}, tsc fails.
    const account: AccountListResponse = { items: [], total: 0 };
    const asEnvelope: ListResponse<AccountListResponse["items"][number]> = account;
    const backAgain: AccountListResponse = asEnvelope;
    expect(backAgain.total).toBe(0);

    // A representative assignment for every other wrapper keeps them pinned to
    // the generic without re-declaring the envelope inline.
    const wrappers: ListResponse<unknown>[] = [
      account satisfies ListResponse<unknown>,
      { items: [], total: 0 } satisfies JournalEntryListResponse,
      { items: [], total: 0 } satisfies BankStatementListResponse,
      { items: [], total: 0 } satisfies UnmatchedTransactionsResponse,
      { items: [], total: 0 } satisfies ReconciliationMatchListResponse,
      { items: [], total: 0 } satisfies ManagedPositionListResponse,
      { items: [], total: 0 } satisfies ManualValuationSnapshotListResponse,
      { items: [], total: 0 } satisfies ProcessingPendingListResponse,
    ];
    expect(wrappers).toHaveLength(8);

    // Source-scan: the `{ items: …[]; total: number }` envelope appears exactly
    // once in types.ts — the generic definition. Any re-introduced per-entity
    // duplicate would push the count above one and fail here.
    const typesSource = readFileSync(resolve(__dirname, "../lib/types.ts"), "utf8");
    const inlineEnvelope = /items:\s*[A-Za-z0-9_]+\[\];\s*\n\s*total:\s*number;/g;
    expect(typesSource.match(inlineEnvelope)).toHaveLength(1);
    expect(typesSource).toContain("export interface ListResponse<T> {");
  });

  it("AC25.3.1: OpenAPI-mirrored contract types resolve to a real generated Schemas key (drift guard)", () => {
    // These compile-time references fail `tsc` if the backend renames/removes a
    // schema and the generated `api-types.ts` is regenerated, surfacing FE↔BE
    // contract drift instead of letting it pass silently.
    const account: Schemas["AccountResponse"] | null = null;
    const journal: Schemas["JournalEntryResponse"] | null = null;
    const balanceSheet: Schemas["BalanceSheetResponse"] | null = null;
    const income: Schemas["IncomeStatementResponse"] | null = null;
    const cashFlow: Schemas["CashFlowResponse"] | null = null;
    const statement: Schemas["BankStatementResponse"] | null = null;

    expect([account, journal, balanceSheet, income, cashFlow, statement]).toEqual([
      null,
      null,
      null,
      null,
      null,
      null,
    ]);
  });

  // AC-meta.fe-contract-types.2
  it("AC25.3.2: lib/api.ts is the single raw-fetch boundary in the frontend", () => {
    const sourceFiles: string[] = [];
    const visit = (path: string) => {
      const stat = statSync(path);
      if (stat.isDirectory()) {
        for (const entry of readdirSync(path)) visit(resolve(path, entry));
        return;
      }
      if (!/\.(ts|tsx)$/.test(path)) return;
      if (/\.test\.(ts|tsx)$/.test(path)) return;
      if (path.endsWith("/lib/api.ts")) return; // the sanctioned boundary
      sourceFiles.push(path);
    };
    visit(resolve(__dirname, ".."));

    // Match a bare `fetch(` call but not `refetch(`, `apiFetch(`, or `.fetch(`.
    const rawFetch = /(?<![A-Za-z0-9_.])fetch\(/;
    const offenders = sourceFiles
      .filter((file) => rawFetch.test(readFileSync(file, "utf8")))
      .map((file) => file.replace(resolve(__dirname, "..") + "/", ""));

    expect(offenders).toEqual([]);
  });
});

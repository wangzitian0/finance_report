import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import React, { type ReactNode } from "react";
import { expect, vi } from "vitest";
import type { InvestmentPerformanceReportSchedule, PersonalDataQualityHealthResponse, PortfolioHolding, WorkflowEventListResponse, WorkflowStatusResponse } from "@/lib/types";
import { balanceSheetVector } from "../fixtures/apiVectors";
import { routerReplace, setTestUrl, testUrl } from "./nextNavigation";
import { normalizablePackageDocument } from "./packageDocumentFixture";
import { btn, clk, deferred, dis, en, fBtn, fTxt, has, noTxt, see, tid, fTid, txt } from "./statementTestFixtures";
export { btn, fBtn, qBtn, clk, chg, txt, fTxt, tid, fTid, has, see, noTxt, dis, en, deferred } from "./statementTestFixtures";

const u = (n: string) => `${n.repeat(8)}-${n.repeat(4)}-4${n.repeat(3)}-8${n.repeat(3)}-${n.repeat(12)}`;
const D0 = "2025-05-20", D1 = "2026-05-20", T1 = "2026-05-20T12:00:00Z", P_ID = "personal-financial-report-package";
const PKG_IDS = { stmt: u("1"), entry: u("2"), line: u("3"), doc: u("4"), atomic: u("5"), reportLine: u("6"), decision: u("7") };
type Req = { path?: Record<string, unknown>; query?: Record<string, unknown>; body?: unknown; headers?: HeadersInit; signal?: AbortSignal };

export async function createCompatApiMock(orig: () => Promise<typeof import("@/lib/api")>, fn: (...a: unknown[]) => unknown, dl?: (...a: unknown[]) => unknown) {
  const actual = await orig(), ops = (await import("@/lib/api-operations")).API_OPERATIONS as Record<string, { method: string; path: string }>;
  const call = (f: (...a: unknown[]) => unknown, op: string, r: Req = {}, m = "POST") => {
    const def = ops[op];
    let p = def ? def.path.replace(/\{([^}]+)\}/g, (_m, k: string) => encodeURIComponent(String(r.path?.[k] ?? ""))) : `/${op}`;
    if (r.query) {
      const q = new URLSearchParams();
      for (const [k, raw] of Object.entries(r.query)) if (raw != null) for (const v of Array.isArray(raw) ? raw : [raw]) q.append(k, String(v));
      if (q.toString()) p += `?${q}`;
    }
    const init = r.body !== undefined || r.headers !== undefined || r.signal !== undefined;
    return def?.method === "GET" && !init ? f(p) : f(p, { method: def?.method ?? m, ...(r.body !== undefined ? { body: JSON.stringify(r.body) } : {}), headers: r.headers, signal: r.signal });
  };
  return { ...actual, apiOperation: (op: string, r?: Req) => call(fn, op, r), ...(dl ? { apiOperationDownload: (op: string, r?: Req) => call(dl, op, r, "GET") } : {}) };
}
const makeReadiness = (o: Record<string, unknown> = {}) => ({
  package_id: P_ID, state: "blocked", label: "Blocked", action_href: "/review", blocking_count: 2,
  input_coverage: { manifest_decision_count: 1, authoritative_input_count: 4, unproven_input_count: 2 },
  blockers: [{ code: "pending_review", label: "Pending source review", severity: "blocking", count: 1, reason: "R", action_href: "/review" }, { code: "balance_mismatch", label: "Balance validation mismatch", severity: "blocking", count: 1, reason: "M", action_href: "/review" }],
  generated_at: null, stale_since: null, ...o,
});
const makeBalanceSheet = (o: Record<string, unknown> = {}) => ({ as_of_date: D1, currency: "SGD", assets: [], liabilities: [], equity: [], total_assets: "100000.00", total_liabilities: "35000.00", total_equity: "65000.00", net_income: "25400.00", unrealized_fx_gain_loss: "0.00", net_worth_adjustment_gain_loss: "0.00", equation_delta: "0.00", is_balanced: true, ...o });
const makeIncomeStatement = (o: Record<string, unknown> = {}) => ({ start_date: D0, end_date: D1, currency: "SGD", income: [], expenses: [], total_income: "137400.00", total_expenses: "112000.00", net_income: "25400.00", trends: [], ...o });
export const makeCashFlow = (o: Record<string, unknown> = {}) => ({ start_date: D0, end_date: D1, currency: "SGD", operating: [], investing: [], financing: [], summary: { operating_activities: "31000.00", investing_activities: "-6000.00", financing_activities: "-2500.00", net_cash_flow: "22500.00", beginning_cash: "30000.00", ending_cash: "52500.00" }, ...o });
const makeHolding = (o: Partial<PortfolioHolding> = {}): PortfolioHolding => ({ id: "h1", user_id: "u1", account_id: "acc1", asset_identifier: "AAPL", quantity: "10", cost_basis: "1500.00", market_value: "1800.00", unrealized_pnl: "300.00", unrealized_pnl_percent: "20.00", currency: "USD", native_cost_basis: o.cost_basis ?? "1500.00", native_currency: o.currency ?? "USD", reporting_cost_basis: o.cost_basis ?? "1500.00", reporting_currency: o.currency ?? "USD", acquisition_date: "2025-01-15", status: "active", account_name: "IBKR", asset_type: "Equity", sector: "Technology", geography: "US", ...o });
export const makeSchedule = (o: Record<string, unknown> = {}): InvestmentPerformanceReportSchedule => ({
  period_start: "2026-01-01", period_end: "2026-03-31", as_of_date: "2026-04-01", currency: "SGD", xirr: "8.25", time_weighted_return: "5.00", money_weighted_return: "4.00", dividend_yield: "1.50", realized_pnl: "1200.00", unrealized_pnl: "300.00", dividend_income: "88.00",
  holdings: [{ asset_identifier: "AAPL", quantity: "10", cost_basis: "1000.00", market_value: "1200.00", unrealized_pnl: "200.00", realized_pnl: "0.00", dividend_income: "0.00", currency: "SGD" }, { asset_identifier: "MSFT", quantity: "5", cost_basis: "2000.00", market_value: "2100.00", unrealized_pnl: "100.00", realized_pnl: "0.00", dividend_income: "0.00", currency: "SGD" }],
  allocation: [], data_freshness: { latest_price_date: "2026-04-01", market_data_provider: "IBKR", stale: false, stale_holdings: [], manual_override_basis: null }, source_links: [], notes: [], ...o,
}) as InvestmentPerformanceReportSchedule;
const withIds = <T extends { identifiers: string[] }>(a: T, ids: string[]) => ({
  ...a, identifiers: ids,
  details: ids.map((id) => ({ identifier: id, source_kind: id.split(":")[0], source_id: id.slice(id.indexOf(":") + 1), amount: id.startsWith("journal_line:") ? "120.00" : null, currency: id.startsWith("journal_line:") ? "SGD" : null, review_state: "current_authoritative_decision", decision_id: PKG_IDS.decision, reason_code: null })),
});
const defaultPolicy = {
  result_id: `policy-result:personal_us_gaap_like:${D0}:${D1}:fixture`, framework_id: "personal_us_gaap_like", matrix_version: "1.0", report_period_start: D0, report_period_end: D1, generated_at: D1, required_statements: ["balance_sheet"],
  decisions: [{ domain: "listed_security", recognition: "O", measurement: "Q", classification: "Marketable investment asset.", presentation: "US", disclosure: "P", line_mappings: { balance_sheet: "assets.marketable_securities" }, evidence_anchors: [{ anchor_id: "atomic_position:abc", anchor_type: "atomic_position", source_system: "atomic_positions", source_id: "abc", description: "H" }], provenance: "deterministic_matrix", review_state: "accepted", policy_field_name: "framework_policy_decision", accepted_value: "listed_security" }],
  gaps: [{ code: "unsupported_policy_domain", fact_id: "atomic_position:private-token", domain: "unsupported", instrument_type: "other", blocker: true, reason: "N", remediation: "A", evidence_anchors: [{ anchor_id: "atomic_position:private-token", anchor_type: "atomic_position", source_system: "atomic_positions", source_id: "private-token", description: "T" }] }],
};
const anc = (s: string, k: string, t: string[], ids: string[]) => withIds({ state: s, [k]: t, identifier_fields: ["ids"], identifiers: [] as string[] }, ids);
const defaultAppendix = {
  section_id: "traceability_appendix", label: "Traceability Appendix", status: "ready",
  lines: [
    { line_id: "balance_sheet.total_assets", section_id: "balance_sheet", label: "Total Assets", amount_field: "total_assets", currency_field: "currency", source_state: "posted_reconciled_journal_lines_and_manual_valuations", source_anchor: anc("available", "source_types", ["bank_statement", "manual_valuation_snapshot"], [`statement_transaction:${PKG_IDS.stmt}`, "manual_valuation_snapshot:val-456"]), ledger_anchor: anc("available", "entry_statuses", ["posted", "reconciled"], [`journal_entry:${PKG_IDS.entry}`, `journal_line:${PKG_IDS.line}`]), anchor_count: 4, blocker_codes: [] },
    { line_id: "notes.non_compliance_statement", section_id: "notes", label: "Package Non-Compliance Statement", amount_field: null, currency_field: null, source_state: "package_contract", source_anchor: anc("available", "source_types", ["package_contract"], ["note:basis-of-preparation"]), ledger_anchor: anc("not_applicable", "entry_statuses", [], []), anchor_count: 1, blocker_codes: ["static_contract_note"] },
  ],
  completeness_warnings: [{ code: "manual_only_source", label: "Manual-only source coverage", applies_to_sections: ["balance_sheet"], state: "explicit_manual_input_required" }],
};
function makePackageDoc(r = makeReadiness(), p = defaultPolicy, t: unknown = defaultAppendix, lifecycle: "preview" | "frozen" = "preview", snapshotId: string | null = null) {
  return {
    schema_version: "2" as const, lifecycle, snapshot_id: snapshotId, package_decision_id: lifecycle === "frozen" ? u("8") : null, generated_at: T1, frozen_at: lifecycle === "frozen" ? T1 : null,
    package_id: P_ID, status: (r as { blocking_count: number }).blocking_count === 0 ? "trusted" : "draft",
    context: { framework_id: p.framework_id, start_date: D0, end_date: D1, as_of_date: D1, currency: "SGD" },
    contract: {
      package_id: P_ID, version: "1.0", period_semantics: { decimal_serialization: "string" }, supported_frameworks: ["personal_us_gaap_like", "personal_hkfrs_like"], selected_framework_id: p.framework_id,
      sections: [["balance_sheet", "Balance Sheet"], ["income_statement", "Income Statement"], ["cash_flow", "Cash Flow"], ["investment_performance", "Investment Performance"], ["annualized_income_long_term", "Annualized Income & Long-Term Compensation"], ["notes", "Notes & Disclosures"], ["traceability_appendix", "Traceability Appendix"]].map(([section_id, label]) => ({ section_id, label, owner_epic: "EPIC-005", status: "ready" })),
      export_contract: { formats: ["json", "csv"], csv_columns: ["package_id", "section_id", "line_id", "label", "amount", "currency", "source_state", "selected_framework_id", "framework_policy_result_id", "framework_policy_matrix_version", "evidence_bundle_references"] },
    },
    readiness: r, framework_policy: p,
    input_manifest: [{ decision_id: PKG_IDS.decision, input_refs: [`journal_entry:${PKG_IDS.entry}`], target_kind: "journal_command", target_id: `statement-transaction:${PKG_IDS.stmt}`, target_version: "fixture-v1", assertion_kind: "promotion", assertion_id: "reviewed_statement_posting", assertion_version: "1", authority_tier: "CODE-ONLY" }],
    sections: {
      balance_sheet: makeBalanceSheet(), income_statement: makeIncomeStatement(), cash_flow: makeCashFlow(),
      investment_performance: makeSchedule({ period_start: D0, period_end: D1, as_of_date: D1, xirr: "0.10", dividend_income: "2400.00", dividend_yield: "0.02", holdings: [{ asset_identifier: "ACME", quantity: "10.00", cost_basis: "8000.00", market_value: "10000.00", unrealized_pnl: "2000.00", realized_pnl: "0.00", dividend_income: "240.00", currency: "SGD" }], data_freshness: { latest_price_date: D1, market_data_provider: "fixture", stale: false, stale_holdings: [], manual_override_basis: null }, source_links: ["source_document:brokerage-1"] }),
      annualized_income_long_term: { section_id: "annualized_income_long_term", label: "Annualized Income & Long-Term Compensation", as_of_date: D1, trailing_period_days: 365, income: { annualized_salary: "120000.00", annualized_bonus: "15000.00", annualized_dividend: "2400.00", annualized_total: "137400.00", currency: "SGD", calculation_basis: "12m" }, restricted_holdings: [{ ticker: "SHOP-RSU", compensation_type: "rsu", fair_value: "12500.00", currency: "SGD", valuation_basis: "manual_valuation_snapshot", vesting_schedule: "25%", unlock_date: "2027-01-01" }], restricted_fair_value_total: "12500.00", restricted_fair_value_total_currency: "SGD", net_worth_treatment: { liquid_net_worth_default: "exclude_restricted_holdings" }, notes: ["Personal management report only; not tax advice."] },
      notes: { section_id: "notes", label: "Notes & Disclosures", status: "ready", non_compliance_statement: "This personal management report is not a regulated filing, not legal advice, and not tax advice.", notes: [{ note_id: "basis-of-preparation", label: "Basis of Preparation", owner_epic: "EPIC-005", basis: "package_contract", source_state: "package_contract", applies_to_sections: ["balance_sheet"], disclosure: "S" }, { note_id: "valuation-basis", label: "Valuation Basis", owner_epic: "EPIC-011", basis: "manual_valuation", source_state: "manual_valuation_snapshots", applies_to_sections: ["balance_sheet"], disclosure: "M" }] },
      traceability_appendix: t,
    },
  };
}
function makePackagePreview(r = makeReadiness(), p = defaultPolicy, t: unknown = defaultAppendix) {
  const { snapshot_id: _s, package_decision_id: _d, frozen_at: _f, input_manifest: _m, ...prev } = makePackageDoc(r, p, t);
  const { operating: _o, investing: _i, financing: _fi, ...cf } = prev.sections.cash_flow;
  const full = t as { lines: Array<Record<string, unknown>> };
  const pa = (a: Record<string, unknown>) => { const { identifiers: _ids, details, ...s } = a; return { ...s, detail_count: Array.isArray(details) ? details.length : 0 }; };
  const anchors = [...p.decisions, ...p.gaps].flatMap((i) => i.evidence_anchors ?? []);
  return { ...prev, status: "draft", framework_policy: { ...p, decision_count: p.decisions.length, evidence_reference_count: new Set(anchors.map((a) => `${a.anchor_type}:${a.source_id}`)).size, decisions: p.decisions.slice(0, 25) }, sections: { ...prev.sections, cash_flow: { ...cf, operating: [], investing: [], financing: [], lineage_summary: { event_count: 0, classified_event_count: 0, unclassified_event_count: 0, opening_stock_event_count: 0 } }, traceability_appendix: { ...full, lines: full.lines.map((l) => ({ ...l, source_anchor: pa(l.source_anchor as Record<string, unknown>), ledger_anchor: pa(l.ledger_anchor as Record<string, unknown>) })) } } };
}
const defaultSnapshot = { id: "snap-001", package_id: P_ID, status: "trusted", framework_id: "personal_us_gaap_like", start_date: D0, end_date: D1, as_of_date: D1, currency: "SGD", readiness_state: "ready", is_latest: true, created_at: T1, document: makePackageDoc(makeReadiness({ state: "ready", label: "Ready", blocking_count: 0, blockers: [] }), defaultPolicy, defaultAppendix, "frozen", "snap-001") };
const defaultLineage = {
  anchor: { id: "n5", node_kind: "ledger_line", entity_type: "journal_line", entity_id: PKG_IDS.line, properties: {} },
  nodes: [["n1", "source_document", "uploaded_document", PKG_IDS.doc], ["n2", "extracted_record", "bank_statement_transaction", PKG_IDS.stmt], ["n3", "atomic_fact", "atomic_transaction", PKG_IDS.atomic], ["n4", "ledger_entry", "journal_entry", PKG_IDS.entry], ["n5", "ledger_line", "journal_line", PKG_IDS.line], ["n6", "report_line", "package_traceability_line", PKG_IDS.reportLine]].map(([id, node_kind, entity_type, entity_id]) => ({ id, node_kind, entity_type, entity_id, properties: {} })),
  edges: [["e1", "parsed_into", "upstream", 4, "n1", "n2"], ["e2", "deduped_into", "upstream", 3, "n2", "n3"], ["e3", "posted_as", "upstream", 2, "n3", "n4"], ["e4", "contains", "upstream", 1, "n4", "n5"], ["e5", "aggregated_into", "downstream", 1, "n5", "n6"]].map(([id, relation, direction, depth, from_node_id, to_node_id]) => ({ id, relation, direction, depth, from_node_id, to_node_id, properties: {} })),
  blockers: [], max_depth: 6,
};
function createPackageRouter(r = makeReadiness(), p = defaultPolicy, t: unknown = defaultAppendix, lin: unknown = defaultLineage, snaps: unknown[] = [defaultSnapshot], gen: unknown = defaultSnapshot) {
  return (path: string, opts?: RequestInit) => {
    if (path === "/api/reports/package/snapshots" && opts?.method === "POST") return gen instanceof Error ? Promise.reject(gen) : Promise.resolve(gen);
    if (path === "/api/reports/package/snapshots") return Promise.resolve(snaps);
    if (path === "/api/reports/package/snapshots/snap-001") return Promise.resolve(gen);
    if (path.startsWith("/api/reports/package?")) return Promise.resolve(makePackagePreview(r, p, t));
    if (path.startsWith("/api/reports/package/")) {
      const url = new URL(path, "http://x"), limit = Number(url.searchParams.get("limit")), offset = Number(url.searchParams.get("offset"));
      if (url.pathname.endsWith("/policy-decisions")) return Promise.resolve({ total: p.decisions.length, limit, offset, decisions: p.decisions.slice(offset, offset + limit) });
      if (url.pathname.endsWith("/manifest-entries")) { const entries = makePackageDoc().input_manifest; return Promise.resolve({ total: entries.length, limit, offset, entries: entries.slice(offset, offset + limit) }); }
      const lineId = url.searchParams.get("line_id"), anchor = url.searchParams.get("anchor") as "source_anchor" | "ledger_anchor";
      const details = (t as { lines: Array<{ line_id: string; source_anchor: { details?: unknown[] }; ledger_anchor: { details?: unknown[] } }> }).lines.find((i) => i.line_id === lineId)?.[anchor]?.details ?? [];
      return Promise.resolve({ line_id: lineId, anchor, total: details.length, limit, offset, details: details.slice(offset, offset + limit) });
    }
    if (path.startsWith("/api/statements/evidence-lineage?")) return lin instanceof Error ? Promise.reject(lin) : Promise.resolve(lin);
    return Promise.reject(new Error(`Unexpected ${path}`));
  };
}

// --- Shared RTL & utility helpers ---
type AnyMock = { mockImplementation: (fn: never) => unknown; mock?: { calls: unknown[][] }; mockResolvedValue?: (v: never) => unknown };
const q = (r?: HTMLElement) => (r ? within(r) : screen);
const fClk = async (n: string | RegExp, r?: HTMLElement) => fireEvent.click(await fBtn(n, r));
const clkTxt = (t: string | RegExp, r?: HTMLElement) => fireEvent.click(q(r).getByText(t));
const fClkTxt = async (t: string | RegExp, r?: HTMLElement) => fireEvent.click(await q(r).findByText(t));
const clkLbl = (t: string | RegExp, r?: HTMLElement) => fireEvent.click(q(r).getByLabelText(t));
const qTxt = (t: string | RegExp, r?: HTMLElement) => q(r).queryByText(t);
const allTxt = (t: string | RegExp, r?: HTMLElement) => q(r).getAllByText(t);
const fAllTxt = (t: string | RegExp, r?: HTMLElement) => q(r).findAllByText(t);
const lbl = (t: string | RegExp, r?: HTMLElement) => q(r).getByLabelText(t);
export const fLbl = (t: string | RegExp, r?: HTMLElement) => q(r).findByLabelText(t);
const reg = (n: string | RegExp, r?: HTMLElement) => q(r).getByRole("region", { name: n });
const fReg = (n: string | RegExp, r?: HTMLElement) => q(r).findByRole("region", { name: n });
export const lnk = (n: string | RegExp, r?: HTMLElement) => q(r).getByRole("link", { name: n });
export const fLnk = (n: string | RegExp, r?: HTMLElement) => q(r).findByRole("link", { name: n });
const hdg = (n: string | RegExp, level?: number, r?: HTMLElement) => q(r).getByRole("heading", { name: n, ...(level ? { level } : {}) });
const fHdg = (n: string | RegExp, level?: number, r?: HTMLElement) => q(r).findByRole("heading", { name: n, ...(level ? { level } : {}) });
const fDlg = (n?: string | RegExp) => screen.findByRole("dialog", n ? { name: n } : undefined);
export const hasAny = (items: (string | RegExp)[], r?: HTMLElement) => { for (const x of items) expect(allTxt(x, r).length).toBeGreaterThanOrEqual(1); };
const noAll = (items: (string | RegExp)[], r?: HTMLElement) => { for (const x of items) expect(qTxt(x, r)).toBeNull(); };
const qcWrap = () => {
  const c = new QueryClient({ defaultOptions: { queries: { staleTime: 60_000, retry: false } } });
  return { c, w: { wrapper: ({ children }: { children: ReactNode }) => React.createElement(QueryClientProvider, { client: c }, children) } };
};
const stubBlobUrl = () => {
  const cu = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:p");
  const ru = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  return () => { cu.mockRestore(); ru.mockRestore(); };
};
export const stubUrlAssign = (val = "blob:cash-flow-export") => vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => val), revokeObjectURL: vi.fn() }));
const evReqs = (api: { mock: { calls: unknown[][] } }, pfx: string) => api.mock.calls.map(([p]) => String(p)).filter((p) => p.startsWith(pfx));
const expDates = (p: string, end: string, start: string) => { const sp = new URL(p, "http://x").searchParams; expect([sp.get("start_date"), sp.get("end_date"), sp.get("as_of_date")]).toEqual([start, end, end]); };
export const wfCall = (fn: unknown, ...args: unknown[]) => waitFor(() => expect(fn).toHaveBeenCalledWith(...args));
const wfLastCall = (fn: unknown, ...args: unknown[]) => waitFor(() => expect(fn).toHaveBeenLastCalledWith(...args));
export const mockLink = ({ href, children, ...p }: { href: string; children: ReactNode; [k: string]: unknown }) => React.createElement("a", { href, ...p }, children);
const assertSkeletonLoading = (container: HTMLElement, name: string, min = 10) => {
  expect(screen.getByRole("status", { name })).toHaveAttribute("aria-busy", "true");
  expect(container.querySelectorAll("[data-testid='skeleton-block']").length).toBeGreaterThanOrEqual(min);
  expect(container.querySelector(".animate-spin")).toBeNull();
};
export async function assertLineageTriggers(triggers: (string | HTMLElement)[], memo: string) {
  for (const t of triggers) {
    fireEvent.click(typeof t === "string" ? screen.getByRole("button", { name: t }) : t);
    await waitFor(() => expect(screen.getByText(memo)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Close panel" }));
    await waitFor(() => expect(screen.queryByText(memo)).toBeNull());
  }
}
const pkgManyDec = (n: number) => Array.from({ length: n }, (_u, i) => ({
  ...defaultPolicy.decisions[0],
  evidence_anchors: [{ anchor_id: `journal_line:line-${i}`, anchor_type: "journal_line", source_system: "canonical_ledger", source_id: `line-${i}`, description: "A" }],
  line_mappings: { ...defaultPolicy.decisions[0].line_mappings, balance_sheet: `assets.line_${i}` },
}));
const pkgClosedAudit = (x: string | RegExp) => {
  const d = screen.getAllByText(x).map((n) => n.closest("details")).find((c): c is HTMLDetailsElement => c instanceof HTMLDetailsElement && Boolean(within(c).queryByText(/audit details/i)));
  if (!d) throw new Error(`Missing closed audit: ${x}`);
  expect(d).not.toHaveAttribute("open");
};
const pkgMonthlySnap = () => ({ ...defaultSnapshot, start_date: "2025-03-01", end_date: "2025-03-31", as_of_date: "2025-04-01", document: { ...defaultSnapshot.document, context: { ...defaultSnapshot.document.context, start_date: "2025-03-01", end_date: "2025-03-31", as_of_date: "2025-04-01" } } });
const pkgHkPolicy = () => ({ ...defaultPolicy, result_id: "policy-result:personal_hkfrs_like:2025-05-20:2026-05-20:fixture", framework_id: "personal_hkfrs_like", decisions: [], gaps: [] });
const pkgOtherPolicy = () => {
  const other = { ...defaultPolicy.decisions[0], domain: "personal_income" as const, classification: "Other income", line_mappings: { ...defaultPolicy.decisions[0].line_mappings, income_statement: "income.other" } };
  return { ...defaultPolicy, decisions: [{ ...defaultPolicy.decisions[0], domain: "manual_private_asset", classification: "Private asset.", review_state: "pending_review" }, ...[1, 2, 3].map((i) => ({ ...other, evidence_anchors: [{ anchor_id: `journal_line:${i}`, anchor_type: "journal_line", source_system: "canonical_ledger", source_id: String(i), description: "L" }] }))] };
};
const pkgScopeSections = () => {
  const sec = makePackageDoc().sections;
  const bal = { ...sec.balance_sheet, currency: "SGD", total_assets: "20360.65", total_liabilities: "0.00", excluded_holdings: [{ asset_class: "real_estate", total_assets: "1200000.00", total_liabilities: "650000.00", net_worth: "550000.00", warnings: [] }, { asset_class: "restricted_comp", total_assets: "42000.00", total_liabilities: "0.00", net_worth: "42000.00", warnings: [] }] };
  const { excluded_holdings: _d, ...oldBal } = { ...sec.balance_sheet, excluded_holdings: undefined };
  return { sec, bal, oldBal };
};
const mockBsApi = (api: AnyMock, payload: unknown) => api.mockImplementation(((op: string) => Promise.resolve(op === "balance_sheet_reports_balance_sheet_get" ? payload : { currency: "SGD", granularity: "monthly", points: [] })) as never);
const BS_VAL = () => makeBalanceSheet({ as_of_date: "2026-10-23", assets: [{ account_id: "bank", name: "DBS Savings", type: "ASSET", parent_id: null, amount: "20385.65" }], liabilities: [{ account_id: "loan", name: "Valuation: Condo loan (mortgage balance)", type: "LIABILITY", parent_id: null, amount: "650000.00" }], equity: [{ account_id: "open", name: "Opening Balance", type: "EQUITY", parent_id: null, amount: "15000.00" }], total_assets: "1262385.65", total_liabilities: "650000.00", total_equity: "15000.00", net_income: "5360.65", unrealized_fx_gain_loss: "25.00", cta_adjustment: "0.00", net_worth_adjustment_gain_loss: "592000.00", excluded_holdings: [] });
const BS_EXCL = () => makeBalanceSheet({ as_of_date: "2026-10-23", total_assets: "20360.65", total_liabilities: "0.00", total_equity: "15000.00", net_income: "5360.65", assets: [{ account_id: "bank", name: "DBS Savings", type: "ASSET", parent_id: null, amount: "20360.65" }], equity: [{ account_id: "open", name: "Opening Balance", type: "EQUITY", parent_id: null, amount: "15000.00" }], excluded_holdings: [{ asset_class: "real_estate", total_assets: "1200000.00", total_liabilities: "650000.00", net_worth: "550000.00", warnings: [] }, { asset_class: "restricted_comp", total_assets: "42000.00", total_liabilities: "0.00", net_worth: "42000.00", warnings: [] }, { asset_class: "retirement_and_benefit_assets", total_assets: null, total_liabilities: null, net_worth: null, warnings: [{ type: "missing_fx_rate_excluded_holding", source: "401k", currency: "USD", target_currency: "SGD", message: "No FX rate" }, { type: "fx_conversion_failed_excluded_holding", source: "MPF", currency: "HKD", target_currency: "SGD", message: "invalid FX" }] }] });
const BS_TRANSIT = () => makeBalanceSheet({ as_of_date: "2026-02-01", total_assets: "1100.00", total_liabilities: "0.00", total_equity: "1100.00", assets: [{ account_id: "proc-1", name: "Processing", type: "ASSET", parent_id: null, amount: "-250.00", source_currency: "SGD", native_amount: "-250.00" }, { account_id: "cmb-1", name: "China Merchants Bank ••7788", type: "ASSET", parent_id: null, amount: "0.00", source_currency: "CNY", native_amount: "47939.43" }, { account_id: "usd-1", name: "IBKR USD Cash", type: "ASSET", parent_id: null, amount: "1350.00", source_currency: "USD", native_amount: "1000.00" }], fx_warnings: [{ type: "missing_fx_rate_partial_skip", base_currency: "CNY", quote_currency: "SGD", rate_date: "2026-02-01" }] });
const BS_COLLAPSE = () => makeBalanceSheet({ as_of_date: "2026-02-01", total_assets: -500, total_liabilities: 0, total_equity: 0, equation_delta: 0, assets: [{ account_id: "a-root", name: "Cash", type: "ASSET", parent_id: null, amount: 1000 }, { account_id: "a-child", name: "Wallet", type: "ASSET", parent_id: "a-root", amount: 100 }], opening_balance_warnings: [{ type: "missing_opening_balance", message: "Record opening balances to trust this total." }] });
const BS_CTA = () => ({ ...balanceSheetVector(), cta_adjustment: "142.50", total_assets: "24200.00", total_liabilities: "0.00", total_equity: "15450.75", net_income: "8749.25", equation_delta: "0.00", is_balanced: true, currency: "SGD" });
export const BS_LINEAGE_ASSETS = () => makeBalanceSheet({ as_of_date: "2026-02-01", total_assets: "43000.00", total_liabilities: "0.00", total_equity: "43000.00", assets: [{ account_id: "a-root", name: "Cash", type: "ASSET", parent_id: null, amount: "1000.00", provenance: "manual", allocation_source_type: "ledger_account" }, { account_id: "val-comp-1", name: "Valuation: CPF Ordinary Account (cpf balance)", type: "ASSET", parent_id: null, amount: "42000.00", provenance: "manual", allocation_source_type: "manual_valuation" }] });
export const BS_LINEAGE_RESP = { account_id: "a-root", account_name: "Cash", account_type: "ASSET", currency: "SGD", as_of_date: "2026-02-01", start_date: null, total: "1000.00", lines: [{ journal_line_id: u("8"), journal_entry_id: u("9"), entry_date: "2026-01-15", memo: "Opening deposit", direction: "DEBIT", original_amount: "1000.00", original_currency: "SGD", amount: "1000.00" }] };
const mkWfSt = (o: Record<string, unknown> = {}): WorkflowStatusResponse => ({ primary_state: "ready", next_action: { type: "open_report", count: 1, href: "/reports/package", label: "Open report", summary: "R" }, report_readiness: { state: "ready", blocking_count: 0, href: "/reports/package" }, event_counts: { unread: 0, action_required: 0, blocked: 0 }, active_session: null, ...o }) as WorkflowStatusResponse;
const mkWfEv = (id: string, sev: string, status: string, title: string, src: string, href: string, imp: string) => ({ id, user_id: "u1", session_id: "s1", occurred_at: "2026-06-03T08:00:00Z", family: `${src}.${sev}`, severity: sev, status, title, summary: "S", source_type: src, source_id: id, action_href: href, report_impact: imp, dedupe_key: id, created_at: "2026-06-03T08:00:00Z", updated_at: "2026-06-03T08:00:00Z" });
const WF_SESS = { id: "s1", status: "active", title: "Upload-to-report session", summary: "S", started_at: "2026-06-03T05:00:00Z", last_event_at: "2026-06-03T08:00:00Z", source_count: 4, primary_state: "needs_action", report_readiness: { state: "blocked", blocking_count: 2, href: "/reports/package" }, event_counts: { unread: 3, action_required: 2, blocked: 1 } };
export const WF_ST_ACT = mkWfSt({ primary_state: "needs_action", next_action: { type: "review_required", count: 2, href: "/inbox", label: "Review required", summary: "C" }, report_readiness: { state: "blocked", blocking_count: 2, href: "/reports/package" }, event_counts: { unread: 3, action_required: 2, blocked: 1 }, active_session: WF_SESS });
const WF_ST_EMPTY = mkWfSt({ primary_state: "empty", next_action: { type: "upload", count: 0, href: "/upload", label: "Upload statements", summary: "A" }, report_readiness: { state: "none", blocking_count: 0, href: "/reports/package" } });
export const WF_EVS: WorkflowEventListResponse = { total: 4, items: [mkWfEv("e1", "blocked", "unread", "Reconciliation blocked", "reconciliation", "/reconciliation?tab=unmatched", "blocked") as never, mkWfEv("e2", "action_required", "unread", "Review required", "bank_statement", "/inbox", "blocked") as never, mkWfEv("e3", "success", "read", "Safe entries posted", "journal", "/journal", "ready") as never, mkWfEv("e4", "info", "read", "Statement uploaded", "bank_statement", "/statements/s4", "processing") as never], sessions: [WF_SESS as never] };
const CF_LINE_OP = "list_cash_flow_line_events_reports_cash_flow_line_events_get";
const cfLineEvt = (id: string, memo: string, amount: string, entry_date: string) => ({ journal_entry_id: id, journal_line_ids: [`${id}-cash`, `${id}-counter`], source_type: "system", source_id: null, decision_anchor_id: null, decision_authority_state: "anchored", event_types: [], activity: "Operating", reason_code: null, entry_date, memo, amount });
const CF_FULL = () => makeCashFlow({ start_date: "2026-01-01", end_date: "2026-02-01", operating: [{ line_id: "operating-sales", category: "operating", subcategory: "Sales", amount: "1000", description: "Main ops", event_count: 1 }], investing: [{ line_id: "investing-etf", category: "investing", subcategory: "ETF", amount: "-300", description: null, event_count: 1 }], financing: [{ line_id: "financing-loan", category: "financing", subcategory: "Loan", amount: "200", description: null, event_count: 1 }], summary: { operating_activities: "1000", investing_activities: "-300", financing_activities: "200", net_cash_flow: "900", beginning_cash: "5000", ending_cash: "5900" }, fx_warnings: [{ type: "spot_rate_fallback", from_currency: "EUR", to_currency: "SGD", fallback_date: "2026-01-30" }] });
function mockCfLineageApi(api: AnyMock, failOffset = false) {
  api.mockImplementation(((op: string, req?: { query?: { offset?: number } }) => {
    if (op === "cash_flow_reports_cash_flow_get") return Promise.resolve(makeCashFlow({ start_date: "2026-01-01", end_date: "2026-01-31", operating: [{ line_id: "operating-salary", category: "Operating", subcategory: "Salary", amount: "9000.00", description: "Inflow - Salary", account_id: "acc-salary", event_count: 3 }, { line_id: "operating-groceries", category: "Operating", subcategory: "Groceries", amount: "-105.00", description: "Outflow - Groceries", account_id: "acc-groceries", event_count: 201 }], summary: { operating_activities: "8895.00", investing_activities: "0.00", financing_activities: "0.00", net_cash_flow: "8895.00", beginning_cash: "0.00", ending_cash: "8895.00" }, lineage_summary: { event_count: 204, classified_event_count: 204, unclassified_event_count: 0, opening_stock_event_count: 0 }, proof_state: "proven", proof_reasons: [] }));
    if (op === "account_lineage_reports_account_lineage_get") return Promise.resolve({ account_id: "acc-salary", account_name: "Salary", account_type: "INCOME", currency: "SGD", as_of_date: "2026-01-31", start_date: "2026-01-01", total: "9000.00", lines: [] });
    if (op === CF_LINE_OP) {
      const offset = req?.query?.offset ?? 0;
      if (failOffset && offset > 0) return Promise.reject(new Error("events page failed"));
      return Promise.resolve({ line_id: "operating-groceries", total: 201, limit: 200, offset, events: offset === 0 ? [cfLineEvt("entry-1", "Groceries Jan 3", "-40.00", "2026-01-03"), cfLineEvt("entry-2", "Groceries Jan 9", "-25.00", "2026-01-09")] : [cfLineEvt("entry-3", "Groceries Jan 12", "-40.00", "2026-01-12")] });
    }
    return Promise.resolve({});
  }) as never);
}
const IS_EMPTY = () => makeIncomeStatement({ start_date: "2026-01-01", end_date: "2026-02-01", total_income: 0, total_expenses: 0, net_income: 0 });
export const IS_FILLED = () => makeIncomeStatement({ start_date: "2026-01-01", end_date: "2026-02-01", income: [{ account_id: "i1", name: "Salary", type: "INCOME", amount: "5000", provenance: "imported" }], expenses: [{ account_id: "e1", name: "Rent", type: "EXPENSE", amount: "1200", provenance: "manual" }], total_income: "5000", total_expenses: "1200", net_income: "3800", fx_warnings: [{ type: "missing_average_rate", from_currency: "USD", to_currency: "SGD", date: "2026-01-31" }], trends: [{ period_start: "2026-01-01", period_end: "2026-01-31", total_income: "5000", total_expenses: "1200", net_income: "3800" }] });
export const IS_LINEAGE = { account_id: "i1", account_name: "Salary", account_type: "INCOME", currency: "SGD", as_of_date: "2026-02-01", start_date: "2026-01-01", total: "5000.00", lines: [{ journal_line_id: u("a"), journal_entry_id: u("b"), entry_date: "2026-01-25", memo: "January payroll", direction: "CREDIT", original_amount: "5000.00", original_currency: "SGD", amount: "5000.00" }] };

export const HD_ACTIVE = makeHolding({ cost_basis_method: "FIFO" });
export const HD_DISPOSED = makeHolding({ id: "h2", quantity: "5", cost_basis: "700.00", market_value: "0.00", unrealized_pnl: "0.00", unrealized_pnl_percent: "0.00", acquisition_date: "2024-06-01", disposal_date: "2025-02-01", status: "disposed", cost_basis_method: "FIFO" });
const HD_DIV = { id: "d1", ex_date: "2026-02-10", pay_date: "2026-02-15", amount: "42.50", currency: "USD", reinvested: false };
const HD_LOT = { lot_id: "11111111-2222-3333-4444-555555555555", acquired_date: "2025-01-15", sold_date: "2026-03-01", quantity: "5.000000", basis: "500.00", proceeds: "650.00", gain_loss: "150.00", holding_period: 410, currency: "USD" };
export const HD_LABELS = { sum: ["Cost Basis", "Active Lots", "Disposed Lots", "FIFO method", "10.123456789"], div: ["Dividend Events", "Ex Date", "Pay Date", "Amount", "Currency", "Reinvested", "$42.50"], lot: ["Lot", "Acquired", "Sold", "Basis", "Proceeds", "Gain/Loss", "$150.00"] };
export function mockDetailApi(api: AnyMock, holdings = [HD_ACTIVE]) {
  api.mockImplementation(((op: string) => {
    if (op === "get_holdings_portfolio_holdings_get") return Promise.resolve({ items: holdings, total: holdings.length, warnings: [] });
    if (op === "get_holding_dividends_portfolio__ticker__dividends_get") return Promise.resolve([HD_DIV]);
    if (op === "get_holding_realized_lots_portfolio__ticker__realized_get") return Promise.resolve([HD_LOT]);
    if (op === "update_holding_cost_basis_method_portfolio__ticker__patch") return Promise.resolve({ updated_count: 1, cost_basis_method: "LIFO" });
    return Promise.reject(new Error(`unhandled operation ${op}`));
  }) as never);
}
const PRICE_HOLDINGS_RES = { items: [makeHolding(), makeHolding({ id: "h2", asset_identifier: "TSLA", quantity: "5", cost_basis: "1000.00", market_value: "900.00" })], total: 2, warnings: [] };
const PRICE_OK_RES = { updated_count: 1, results: [{ success: true, message: "Updated", asset_identifier: "AAPL", price_date: "2026-04-06", price: "180.00", currency: "USD", source: "manual" }] };
const priceForm = () => screen.getByText("Update Prices").closest("form") as HTMLFormElement;
const fillPriceInputs = (tickerVal: string | null, priceVal: string) => {
  if (tickerVal !== null) fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value: tickerVal } });
  fireEvent.change(screen.getByPlaceholderText("0.00"), { target: { value: priceVal } });
};
const checkPriceRows = () => {
  fireEvent.click(screen.getByRole("button", { name: "Add Row" }));
  expect(screen.getAllByRole("combobox")).toHaveLength(2);
  fireEvent.click(screen.getAllByLabelText("Remove row")[1]);
  expect(screen.getAllByRole("combobox")).toHaveLength(1);
};
const checkPriceCurrencyDate = () => {
  const ticker = screen.getByPlaceholderText("AAPL, MSFT...");
  expect(ticker.tagName).toBe("INPUT");
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  const cur = screen.getAllByDisplayValue("USD")[0], dt = screen.getByDisplayValue(/^\d{4}-\d{2}-\d{2}$/);
  fireEvent.change(cur, { target: { value: "eur" } }); expect(cur).toHaveValue("EUR");
  fireEvent.change(dt, { target: { value: "2026-01-15" } }); expect(dt).toHaveValue("2026-01-15");
  fireEvent.change(ticker, { target: { value: "GOOG" } });
  fillPriceInputs(null, "100.00");
};
const HT_BASE = makeHolding({ id: "h1", asset_identifier: "FOO", quantity: "10.5", cost_basis: "1000.00", market_value: "1200.00", unrealized_pnl: "200.00", unrealized_pnl_percent: "20.00", account_name: "BrokerA", sector: undefined });
export const HT_PAIR = [HT_BASE, { ...HT_BASE, id: "d1", status: "disposed" as const, asset_identifier: "GONE" }];
export const HT_GROUPED = [makeHolding({ id: "h2", account_id: "acc2", asset_identifier: "BAR", quantity: "2", cost_basis: "200.00", market_value: "210.00", unrealized_pnl: "10.00", unrealized_pnl_percent: "5.00", account_name: "BrokerB" }), makeHolding({ id: "h3", account_id: "acc2", asset_identifier: "BAZ", quantity: "3", cost_basis: "300.00", market_value: "250.00", unrealized_pnl: "-50.00", unrealized_pnl_percent: "-16.67", account_name: "BrokerB" })];
export const HT_ZERO_PNL = [{ ...HT_BASE, unrealized_pnl: "0.00", unrealized_pnl_percent: "0.00", sector: "Technology", account_name: undefined }];
export const HT_PROVENANCE = [
  { ...HT_BASE, id: "imp", asset_identifier: "IMP", provenance: "imported" as const },
  { ...HT_BASE, id: "man", asset_identifier: "MAN", provenance: "manual" as const },
  { ...HT_BASE, id: "drv", asset_identifier: "DRV", provenance: "derived" as const },
  { ...HT_BASE, id: "unk", asset_identifier: "UNK", provenance: null },
  { ...HT_BASE, id: "hk", asset_identifier: "0700", currency: "SGD", native_currency: "HKD" },
  { ...HT_BASE, id: "sg", asset_identifier: "D05", currency: "SGD", native_currency: "SGD" },
];

export const IPS_STALE = makeSchedule({
  time_weighted_return: null, money_weighted_return: "not-a-number", dividend_yield: "-1.50", unrealized_pnl: "-300.00",
  holdings: [{ asset_identifier: "AAPL", quantity: "10", cost_basis: "3000.00", market_value: "2700.00", unrealized_pnl: "-300.00", realized_pnl: "0.00", dividend_income: "0.00", currency: "SGD" }],
  data_freshness: { latest_price_date: null, market_data_provider: null, stale: true, stale_holdings: ["AAPL", "0700.HK"], manual_override_basis: "manual broker statement" },
});
export const IPS_CURR = {
  ...IPS_STALE, xirr: "0.00", money_weighted_return: "0.00",
  data_freshness: { latest_price_date: "2026-04-01", market_data_provider: "manual", stale: false, manual_override_basis: null },
  source_links: ["statement:aapl"], notes: ["Reviewed manually"],
};
export const IPS_STALE_TEXTS = ["Market-value performance", "Return on Cost", "Analytical return measures (reporting only)", "Status: Stale", "Stale holdings: AAPL, 0700.HK", "Manual override: manual broker statement", "No source links available"];
export const IPS_CURR_TEXTS = ["Status: Current", "statement:aapl", "Reviewed manually"];

// --- Compact test-flow helpers ---
export async function assertReportLoadingError(api: AnyMock & { mockRejectedValue: (e: unknown) => unknown }, Page: React.ComponentType, statusName: string, errMsg: string, minBlocks = 10, retryOp?: string) {
  api.mockRejectedValue(new Error(errMsg));
  const { container } = render(React.createElement(Page));
  assertSkeletonLoading(container, statusName, minBlocks);
  await see(errMsg);
  clk("Retry");
  if (retryOp) await waitFor(() => expect((api as unknown as { mock: { calls: unknown[][] } }).mock.calls.filter(([op]) => op === retryOp)).toHaveLength(2));
  else expect(api).toHaveBeenCalled();
}
export async function runPriceKnown(api: AnyMock, showToastMock: unknown, Form: React.ComponentType<{ knownTickers: string[] }>) {
  api.mockImplementation(((op: string) => Promise.resolve(op === "create_price_overrides_pricing_price_overrides_post" ? PRICE_OK_RES : PRICE_HOLDINGS_RES)) as never);
  render(React.createElement(Form, { knownTickers: ["AAPL", "TSLA"] }));
  expect(txt("Update Prices")).toBeInTheDocument();
  await waitFor(() => expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(expect.arrayContaining(["AAPL", "TSLA"])));
  fireEvent.submit(priceForm());
  expect(showToastMock).toHaveBeenCalledWith("Add at least one price update", "error");
  checkPriceRows();
  fillPriceInputs("AAPL", "180.00"); fireEvent.submit(priceForm());
  await wfCall(api, "create_price_overrides_pricing_price_overrides_post", expect.anything());
  await wfCall(showToastMock, "Updated 1 price(s)", "success");
}
export async function runPriceText(api: AnyMock & { mockRejectedValueOnce: (e: unknown) => unknown; mockResolvedValueOnce: (v: unknown) => unknown }, showToastMock: unknown, Form: React.ComponentType<{ knownTickers: string[]; onSuccess?: () => void }>) {
  api.mockRejectedValueOnce(new Error("Network error"));
  const onSuccess = vi.fn();
  render(React.createElement(Form, { knownTickers: [], onSuccess }));
  checkPriceCurrencyDate(); fireEvent.submit(priceForm());
  await wfCall(showToastMock, "Failed: Network error", "error");
  api.mockResolvedValueOnce(PRICE_OK_RES); fireEvent.submit(priceForm());
  await wfCall(showToastMock, "Updated 1 price(s)", "success");
  await waitFor(() => expect(onSuccess).toHaveBeenCalled());
}
export async function runHdErrorStates(api: AnyMock & { mockRejectedValue: (e: unknown) => unknown; mock: { calls: unknown[][] } }, Detail: React.ComponentType<{ ticker: string }>) {
  api.mockImplementation(((op: string) => (op === "get_holdings_portfolio_holdings_get" ? new Promise(() => {}) : Promise.resolve([]))) as never);
  const v1 = render(React.createElement(Detail, { ticker: "AAPL" })); expect(txt("Loading holding details...")).toBeInTheDocument(); v1.unmount();
  api.mockRejectedValue(new Error("server error"));
  const v2 = render(React.createElement(Detail, { ticker: "AAPL" })); await see("Failed to load holding"); expect(txt("server error")).toBeInTheDocument();
  const n = api.mock.calls.length; fireEvent.click(txt("Retry")); await waitFor(() => expect(api.mock.calls.length).toBeGreaterThan(n)); v2.unmount();
  mockDetailApi(api, [makeHolding({ id: "h3", asset_identifier: "TSLA" })]);
  render(React.createElement(Detail, { ticker: "AAPL" })); await see(/No holdings found for/); expect(txt("AAPL")).toBeInTheDocument();
}
export async function assertIsFilled(api: AnyMock & { mockResolvedValue: (v: unknown) => unknown }, Page: React.ComponentType) {
  api.mockResolvedValue(IS_FILLED());
  render(React.createElement(Page));
  await waitFor(() => expect(hdg("Income Statement")).toBeInTheDocument());
  has(["BarChartMock", "Partial FX data used", "Salary", "Rent"]);
  expect(txt("Imported")).toHaveAccessibleName("Provenance: Imported");
  expect(txt("Manual")).toHaveAccessibleName("Provenance: Manual");
  expect(lnk("AI Interpretation")).toHaveAttribute("href", expect.stringContaining("/chat?prompt="));
  expect(screen.queryByRole("link", { name: "Home" })).toBeNull();
  expect(btn("Export CSV")).toBeInTheDocument();
  for (const [k, v] of [["Total Income", "5,000.00"], ["Total Expenses", "1,200.00"], ["Net Income", "3,800.00"]]) expect(txt(k).closest("div")).toHaveTextContent(v);
}
export async function assertIsTagsDates(api: AnyMock & { mockResolvedValue: (v: unknown) => unknown; mock: { calls: unknown[][] } }, Page: React.ComponentType) {
  api.mockResolvedValue(IS_EMPTY()); setTestUrl("/reports?tab=income-statement&period=1Q&end=2026-03-31");
  const { container } = render(React.createElement(Page));
  await see("No trend data yet."); has(["No income categories.", "No expense categories."]);
  expect(container.querySelector('input[type="date"]')).toBeNull();
  clk("Business"); await waitFor(() => expect(api.mock.calls.at(-1)?.[1]).toMatchObject({ query: { tags: ["business"] } }));
  clk("Personal"); clk("Business"); await waitFor(() => expect(api.mock.calls.at(-1)?.[1]).toMatchObject({ query: { tags: ["personal"] } }));
  await fClk("Clear all"); await waitFor(() => expect(screen.queryByRole("button", { name: "Clear all" })).not.toBeInTheDocument());
  fireEvent.change(screen.getAllByRole("combobox")[1], { target: { value: "INCOME" } });
  await waitFor(() => expect(api.mock.calls.at(-1)).toEqual(["income_statement_reports_income_statement_get", expect.objectContaining({ query: expect.objectContaining({ account_type: "INCOME", start_date: "2026-01-01", end_date: "2026-03-31" }) })]));
  clk("Previous period");
  await waitFor(() => expect(api.mock.calls.at(-1)).toEqual(["income_statement_reports_income_statement_get", expect.objectContaining({ query: expect.objectContaining({ account_type: "INCOME", start_date: "2025-10-01", end_date: "2025-12-31" }) })]));
  expect(btn("Period 1Q")).toHaveAttribute("aria-pressed", "true");
}

export const CF_RECON_CASES = [
  [{ summary: { operating_activities: "0", investing_activities: "0", financing_activities: "0", net_cash_flow: "900", beginning_cash: "5000", ending_cash: "6500" } }, ["⚠ Does not tie", "the reported ending is higher than expected"], /differs from the reported ending/i, ["-"]],
  [{ summary: { operating_activities: "20", investing_activities: "0", financing_activities: "0", net_cash_flow: "20", beginning_cash: "0", ending_cash: "120" }, cash_bridge: { opening_stock_adjustment: "100", reconciles: true }, proof_state: "unproven", proof_reasons: ["opening_coverage_starts_after_period"] }, ["Opening balance adjustment", "100.00", "Coverage incomplete"], /records start after the selected period begins/i, ["✓ Reconciles", "Does not tie"]],
  [{ summary: { operating_activities: "20", investing_activities: "0", financing_activities: "0", net_cash_flow: "20", beginning_cash: "100", ending_cash: "120" }, cash_bridge: { reconciles: true }, proof_state: "unproven", proof_reasons: ["opening_position_unproven"] }, ["Not yet verified"], /opening balance evidence needs review/i, ["✓ Reconciles"]],
] as const;
export async function assertCfFullAndSankey(api: AnyMock & { mockResolvedValue: (v: unknown) => unknown }, Page: React.ComponentType) {
  api.mockResolvedValue(CF_FULL()); render(React.createElement(Page));
  await waitFor(() => expect(hdg("Cash Flow Statement")).toBeInTheDocument());
  has(["Operating Activities", "Investing Activities", "Financing Activities", "Partial FX data used", "Sales", "Main ops", "SankeyChartMock"]);
  expect(lnk("AI Interpretation")).toHaveAttribute("href", expect.stringContaining("/chat?prompt="));
  expect(screen.queryByRole("link", { name: "Home" })).toBeNull();
  for (const [k, v] of [["Net Cash Flow", "900.00"], ["Beginning Cash", "5,000.00"], ["Ending Cash", "5,900.00"]]) expect(txt(k).closest("div")).toHaveTextContent(v);
  expect(lbl("Cash reconciliation")).toHaveTextContent("✓ Reconciles");
}
export async function assertCfLineageAndPaging(api: AnyMock & { mock: { calls: unknown[][] } }, Page: React.ComponentType) {
  mockCfLineageApi(api);
  const v1 = render(React.createElement(Page));
  await fClk(/View source transactions for Salary/i); const dialog = await fDlg();
  await wfCall(api, "account_lineage_reports_account_lineage_get", expect.objectContaining({ query: expect.objectContaining({ account_id: "acc-salary" }) }));
  clk(/close/i, dialog); await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  const calls = () => api.mock.calls.filter(([op]) => op === CF_LINE_OP);
  expect(calls()).toHaveLength(0); noTxt("Groceries Jan 3");
  const toggle = btn("201 events for Outflow - Groceries"); expect(toggle).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(toggle); const events = await fReg("Events for Outflow - Groceries");
  await see("Groceries Jan 3", events); expect(txt("2 of 201 events", events)).toBeInTheDocument();
  expect(calls()[0][1]).toMatchObject({ query: { start_date: "2026-01-01", end_date: "2026-01-31", currency: "SGD", line_id: "operating-groceries", limit: 200, offset: 0 } });
  clk("Load more events", events); await see("Groceries Jan 12", events);
  expect(txt("3 of 201 events", events)).toBeInTheDocument(); expect(calls()).toHaveLength(2);
  clk("201 events for Outflow - Groceries"); expect(screen.queryByRole("region", { name: "Events for Outflow - Groceries" })).not.toBeInTheDocument();
  clk("201 events for Outflow - Groceries"); await see("Groceries Jan 12"); expect(calls()).toHaveLength(2); v1.unmount();

  mockCfLineageApi(api, true); render(React.createElement(Page));
  await fClk("201 events for Outflow - Groceries"); const ev2 = await fReg("Events for Outflow - Groceries");
  await see("Groceries Jan 3", ev2); clk("Load more events", ev2);
  await see("events page failed", ev2); expect(txt("Groceries Jan 3", ev2)).toBeInTheDocument();
}
export async function assertCfExportAndPeriod(api: AnyMock & { mockResolvedValue: (v: never) => unknown }, dl: AnyMock & { mockResolvedValue: (v: never) => unknown }, Page: React.ComponentType) {
  api.mockResolvedValue(makeCashFlow({ start_date: "2026-01-01", end_date: "2026-01-31", summary: { operating_activities: 0, investing_activities: 0, financing_activities: 0, net_cash_flow: 0, beginning_cash: 0, ending_cash: 0 } }) as never);
  dl.mockResolvedValue({ blob: new Blob(["section,account,amount\n"], { type: "text/csv" }), filename: "cash-flow-2026-01-01-to-2026-01-31.csv" } as never);
  setTestUrl("/reports?tab=cash-flow&period=1M&end=2026-01-31&currency=SGD");
  const v1 = render(React.createElement(Page)); await fClk("Export CSV");
  await wfCall(dl, "export_report_reports_exports_get", expect.objectContaining({ query: expect.objectContaining({ report_type: "cash-flow", start_date: "2026-01-01", end_date: "2026-01-31", currency: "SGD" }) })); v1.unmount();
  setTestUrl("/reports?tab=cash-flow&period=1M&end=2026-02-28");
  const { container } = render(React.createElement(Page));
  await waitFor(() => expect(hdg("Cash Flow Statement")).toBeInTheDocument());
  expect(container.querySelector('input[type="date"]')).toBeNull();
  fireEvent.change(screen.getByRole("combobox", { name: "Reporting currency" }), { target: { value: "USD" } });
  await wfLastCall(api, "cash_flow_reports_cash_flow_get", expect.objectContaining({ query: expect.objectContaining({ currency: "USD", start_date: "2026-02-01", end_date: "2026-02-28" }) }));
  clk("Previous period");
  await wfLastCall(api, "cash_flow_reports_cash_flow_get", expect.objectContaining({ query: expect.objectContaining({ currency: "USD", start_date: "2026-01-01", end_date: "2026-01-31" }) }));
  expect(allTxt("No items in this category.")).toHaveLength(3);
  clk("Period 1Q"); expect(btn("Period 1Q")).toHaveAttribute("aria-pressed", "true");
}
const WF_HUMANIZE_CASES = [
  ["Package section invariant failed: opening_balance_missing, cash_balance_input_missing, cash_identity_missing", "Upload a bank statement to verify opening and ending cash balances."],
  ["Package section invariant failed: opening_balance_missing", "Opening balance awaits bank statement verification."],
  ["Package section invariant failed: cash_balance_input_missing", "Ending cash balance awaits bank statement verification."],
  ["Package section invariant failed: cash_identity_missing", "Cash account balance awaits bank statement verification."],
  ["Package section invariant failed", "Statement balance check needed"], ["Ordinary", "Ordinary"], [undefined, ""], [null, ""],
] as const;
const WF_ACTION_LINKS = [["unknown", "Open workflow", "/inbox"], ["upload", "Upload statements", "/upload"], ["review_required", "Review required", "/inbox"], ["resolve_blocker", "Resolve blocker", "/reconciliation?tab=unmatched"], ["open_report", "Open report package", "/reports/package"], ["wait", "View processing", "/inbox"]] as const;
export const WF_POLL_CASES = [
  ["session", () => mkWfSt({ active_session: WF_SESS as never })], ["processing", () => mkWfSt({ primary_state: "processing" })],
  ["needs_action", () => mkWfSt({ primary_state: "needs_action" })], ["blocked", () => mkWfSt({ primary_state: "blocked" })],
  ["action_ev", () => mkWfSt({ event_counts: { unread: 0, action_required: 1, blocked: 0 } })], ["blocked_ev", () => mkWfSt({ event_counts: { unread: 0, action_required: 0, blocked: 1 } })],
] as const;
export async function assertWfNotifCenter(fSt: ReturnType<typeof vi.fn>, fEv: ReturnType<typeof vi.fn>, upd: ReturnType<typeof vi.fn>, Comp: React.ComponentType, probe: { wrapper: React.ComponentType<{ children: ReactNode }>; expectNothingInvalidated: () => void; expectDeclaredInvalidated: () => void }) {
  const v1 = render(React.createElement(Comp)); const b = await fBtn(/Workflow events/i);
  await waitFor(() => expect(b).toHaveTextContent("3")); expect(b).toHaveAccessibleName(/2 actions.*1 blocked/i);
  fireEvent.click(b); const d = await fDlg("Workflow events");
  await fHdg("Upload-to-report session", undefined, d);
  expect(within(d).getAllByRole("link", { name: "Open Reconciliation blocked" })[0]).toHaveAttribute("href", "/reconciliation?tab=unmatched");
  fireEvent.click(within(d).getAllByRole("button", { name: "Mark as read" })[0]); await wfCall(upd, "e1", "read");
  fireEvent.click(within(d).getAllByRole("button", { name: "Archive" })[1]); await wfCall(upd, "e2", "archived");
  const attn = lnk(/needs confirmation/i, d); expect(attn).toHaveAttribute("href", "/audit?tab=needs-you");
  fireEvent.click(attn); await waitFor(() => expect(screen.queryByRole("dialog", { name: "Workflow events" })).not.toBeInTheDocument()); v1.unmount();

  fSt.mockResolvedValue(WF_ST_EMPTY); const v2 = render(React.createElement(Comp));
  await waitFor(() => expect(btn(/Workflow events/i)).not.toHaveTextContent("0")); v2.unmount();

  fSt.mockResolvedValue(WF_ST_ACT);
  const v3 = render(React.createElement(Comp), { wrapper: probe.wrapper });
  await fClk(/Workflow events/i); const d3 = await fDlg("Workflow events");
  await waitFor(() => expect(within(d3).getAllByRole("button", { name: "Mark as read" }).length).toBeGreaterThan(0));
  probe.expectNothingInvalidated(); fireEvent.click(within(d3).getAllByRole("button", { name: "Mark as read" })[0]);
  await waitFor(() => probe.expectDeclaredInvalidated()); clk("Close panel", d3); v3.unmount();

  fEv.mockRejectedValue(new Error("err")); render(React.createElement(Comp));
  await fClk(/Workflow events/i); await see("Unable to load workflow events.", await fDlg("Workflow events"));
}
export function assertWfInboxAndFeed(Inbox: React.ComponentType<{ events: unknown[]; sessions: unknown[]; onStatusChange?: (id: string, s: string) => void }>, Feed: React.ComponentType<{ status: WorkflowStatusResponse; events: unknown[] }>) {
  const onCh = vi.fn(), leg = WF_EVS.items.map((e) => ({ ...e, session_id: null }));
  const ib = render(React.createElement(Inbox, { events: leg, sessions: [], onStatusChange: onCh }));
  expect(txt("4 events")).toBeInTheDocument();
  fireEvent.click(screen.getAllByRole("button", { name: "Mark as read" })[0]); expect(onCh).toHaveBeenCalledWith("e1", "read");
  ib.rerender(React.createElement(Inbox, { events: leg.filter((e) => e.severity === "action_required"), sessions: [] })); expect(txt("1 event")).toBeInTheDocument();
  ib.rerender(React.createElement(Inbox, { events: leg.filter((e) => e.severity === "success" || e.severity === "info"), sessions: [] })); expect(txt("2 events")).toBeInTheDocument();
  ib.rerender(React.createElement(Inbox, { events: [], sessions: [] })); expect(txt(/will appear here/i)).toBeInTheDocument(); ib.unmount();

  const fd = render(React.createElement(Feed, { status: WF_ST_ACT, events: WF_EVS.items }));
  expect(txt("2 routine events")).toBeInTheDocument();
  for (const h of [/audit/i, /journal line id/i]) noTxt(h);
  fd.rerender(React.createElement(Feed, { status: WF_ST_EMPTY, events: [] })); expect(txt("No action required")).toBeInTheDocument();
  for (const [tp, lblText, href] of WF_ACTION_LINKS) {
    fd.rerender(React.createElement(Feed, { status: mkWfSt({ primary_state: tp === "upload" ? "empty" : "needs_action", next_action: { type: tp, count: 0, href, label: "", summary: "" } }), events: [WF_EVS.items[3]] }));
    expect(lnk(lblText)).toHaveAttribute("href", href);
  }
}
export async function assertWfNoticesHumanize(fSt: ReturnType<typeof vi.fn>, fEv: ReturnType<typeof vi.fn>, upd: ReturnType<typeof vi.fn>, Notices: React.ComponentType, humanize: (s?: string | null) => string) {
  fSt.mockReturnValueOnce(new Promise<WorkflowStatusResponse>(() => {}));
  const v1 = render(React.createElement(Notices)); await waitFor(() => expect(fEv).toHaveBeenCalledTimes(1));
  expect(txt("Loading workflow status...")).toBeInTheDocument(); v1.unmount();
  fSt.mockRejectedValueOnce(new Error("e")); fEv.mockRejectedValueOnce(new Error("e"));
  const v2 = render(React.createElement(Notices)); await see("Workflow status is unavailable."); v2.unmount();

  render(React.createElement(Notices)); const d = await fTid("upload-workflow-summary");
  expect(d.tagName).toBe("DETAILS"); expect(d).not.toHaveAttribute("open");
  expect(d.querySelector("summary")).toHaveTextContent("Workflow: Needs Action · 1 blocker · 2 actions · 4 events");
  fireEvent.click(screen.getAllByRole("button", { name: "Mark as read" })[0]); await wfCall(upd, "e1", "read");
  for (const [inp, out] of WF_HUMANIZE_CASES) expect(humanize(inp)).toBe(out);
}
export async function assertWfPollingAdaptive(
  fSt: ReturnType<typeof vi.fn>,
  useHook: () => { result?: unknown },
  hasPending: (s?: WorkflowStatusResponse) => boolean,
  key: readonly unknown[],
  staleMs: number,
  pendingMs: number,
  idleMs: number,
) {
  const adv = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
  fSt.mockResolvedValueOnce(mkWfSt({ primary_state: "processing" })).mockResolvedValue(mkWfSt());
  renderHook(() => useHook()); await waitFor(() => expect(fSt).toHaveBeenCalledTimes(1));
  await adv(pendingMs); expect(fSt).toHaveBeenCalledTimes(2);
  await adv(pendingMs); expect(fSt).toHaveBeenCalledTimes(2);
  await adv(idleMs - pendingMs); expect(fSt).toHaveBeenCalledTimes(3);

  fSt.mockReset(); fSt.mockResolvedValue(mkWfSt()); const { c, w } = qcWrap();
  const h = renderHook(() => useHook(), w); await waitFor(() => expect(fSt).toHaveBeenCalledTimes(1));
  const obs = c.getQueryCache().find({ queryKey: key })?.observers[0];
  expect(obs?.options.refetchOnWindowFocus).toBe(true); expect(obs?.options.staleTime).toBe(staleMs);
  h.unmount(); renderHook(() => useHook(), w); await adv(100); expect(fSt).toHaveBeenCalledTimes(1);

  expect([hasPending(undefined), hasPending(mkWfSt()), hasPending({} as WorkflowStatusResponse)]).toEqual([true, false, true]);
  fSt.mockReset(); fSt.mockResolvedValue({});
  const v = renderHook(() => useHook()) as unknown as { result: { current: { isError: boolean } } };
  await waitFor(() => expect(fSt).toHaveBeenCalledTimes(1));
  await adv(pendingMs); expect(fSt).toHaveBeenCalledTimes(2); expect(v.result.current.isError).toBe(false);
}

export async function assertBsVectorAndDate(api: AnyMock & { mockResolvedValue: (v: unknown) => unknown; mock: { calls: unknown[][] } }, Page: React.ComponentType) {
  const vector = balanceSheetVector(); api.mockResolvedValue(vector);
  const { container, unmount } = render(React.createElement(Page));
  await waitFor(() => expect(hdg("Balance Sheet")).toBeInTheDocument());
  for (const h of ["Assets", "Liabilities", "Equity"]) expect(hdg(h, 2)).toBeInTheDocument();
  has(["Partial FX data used", "Balance Equation Detail", "CTA Adjustment", "Included", "Vector Bank Checking", "Vector Credit Card", "Vector Opening Balances"]);
  expect(vector.total_assets).toBe("9500.00");
  expect(txt("Manual")).toHaveAccessibleName("Provenance: Manual");
  expect(txt("Derived")).toHaveAccessibleName("Provenance: Derived");
  expect(allTxt("Imported")[0]).toHaveAccessibleName("Provenance: Imported");
  expect(allTxt(/Total:/)).toHaveLength(3);
  expect(api).toHaveBeenCalledWith("balance_sheet_reports_balance_sheet_get", expect.objectContaining({ query: expect.objectContaining({ include_restricted: true }) }));
  clkLbl("Include restricted holdings");
  const bsCalls = () => api.mock.calls.filter(([id]) => id === "balance_sheet_reports_balance_sheet_get");
  await waitFor(() => expect(bsCalls().at(-1)?.[1]).toEqual(expect.objectContaining({ query: expect.objectContaining({ include_restricted: false }) })));
  clk("Period 1M"); clk("Previous period");
  const d = new Date(new Date().getFullYear(), new Date().getMonth(), 0);
  const expectedDate = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  await waitFor(() => expect(bsCalls().at(-1)?.[1]).toEqual(expect.objectContaining({ query: expect.objectContaining({ as_of_date: expectedDate }) })));
  expect(container.querySelector('input[type="date"]')).toBeNull(); expect(btn("Period 1M")).toHaveAttribute("aria-pressed", "true"); unmount();
  setTestUrl("/reports?tab=balance-sheet&include_restricted=true");
  api.mockResolvedValue(makeBalanceSheet({ as_of_date: "2026-02-01", assets: [{ account_id: "a-root", name: "Cash", type: "ASSET", parent_id: null, amount: "1000", provenance: "imported" }, { account_id: "restricted-root", name: "Four Asset ESOP", type: "ASSET", parent_id: null, amount: "42000", provenance: "manual" }], total_assets: "43000", total_liabilities: "0", total_equity: "43000" }));
  render(React.createElement(Page)); expect(await fLbl("Include restricted holdings")).toBeChecked();
}
export async function assertBsValuationAndExcluded(api: AnyMock, Page: React.ComponentType) {
  mockBsApi(api, BS_VAL()); const v1 = render(React.createElement(Page));
  expect(await fTid("equity-fx-cta")).toHaveTextContent("FX and translation (CTA):SGD 25.00");
  expect(tid("equity-valuations")).toHaveTextContent("Manual and market valuations:SGD 592,000.00");
  noTxt(/FX\/CTA/); expect(txt("Total:", hdg("Equity", 2).closest("div")!).nextElementSibling).toHaveTextContent("SGD 612,385.65");
  expect(screen.queryByTestId("excluded-holdings-note")).toBeNull(); v1.unmount();
  setTestUrl("/reports?tab=balance-sheet&include_restricted=false"); mockBsApi(api, BS_EXCL());
  render(React.createElement(Page));
  expect(await fTid("excluded-holdings-note")).toHaveTextContent("Excludes restricted and illiquid holdings:Real Estate SGD 550,000.00 (net of SGD 650,000.00 liabilities)Restricted Comp SGD 42,000.00Retirement & Benefit Assets: amount not available (FX conversion failed for HKD to SGD, no FX rate for USD to SGD)");
  expect(txt("Excluded")).toBeInTheDocument(); expect(screen.queryByTestId("equity-valuations")).toBeNull();
}
export async function assertBsTransitCollapseCta(api: AnyMock, Page: React.ComponentType) {
  mockBsApi(api, BS_TRANSIT()); const v1 = render(React.createElement(Page));
  await fBtn("Transfers in transit"); expect(screen.queryByRole("button", { name: "Processing" })).toBeNull();
  expect(screen.getByRole("img", { name: /Transfers in transit:/i })).toBeInTheDocument();
  has([/CN¥47,939\.43/, /No FX rate/i, /\$1,000\.00/, /CNY to SGD on 2026-02-01/]); v1.unmount();
  mockBsApi(api, BS_COLLAPSE()); const v2 = render(React.createElement(Page));
  await see("Wallet"); clk(/Collapse/i); noTxt("Wallet");
  has(["Opening balances not recorded", "✓ Balanced"]); expect(lnk(/set opening balances/i)).toHaveAttribute("href", "/settings?tab=accounts"); v2.unmount();
  mockBsApi(api, BS_CTA()); render(React.createElement(Page));
  await see("CTA Adjustment"); expect(tid("equation-detail-cta")).toHaveTextContent("142.50");
  expect(tid("balance-equation-detail").tagName.toLowerCase()).toBe("details"); expect(txt("Books in balance")).toBeInTheDocument();
  has(["Opening Equity:", "Net Income (P&L):", /15,450\.75/, /8,749\.25/, /24,342\.50/], document.getElementById("equity")!);
}
const pkgFw = async (b = "US-like") => fireEvent.click(await fBtn(b));
export async function assertPkgPeriodAndReopen(api: AnyMock & { mockClear: () => void; mock: { calls: unknown[][] } }, readFilters: (p: URLSearchParams) => { startDate: string; endDate: string }, Page: React.ComponentType) {
  api.mockImplementation(createPackageRouter() as never); setTestUrl("/reports?tab=package&period=1M&end=2025-03-31&currency=SGD");
  const v1 = render(React.createElement(Page)); await pkgFw(); await fClk(/Generate Snapshot/i);
  expDates(evReqs(api, "/api/reports/package?").find((p) => p.includes("framework_id=personal_us_gaap_like"))!, "2025-03-31", "2025-03-01");
  await wfCall(api, "/api/reports/package/snapshots", expect.objectContaining({ method: "POST", body: JSON.stringify({ framework_id: "personal_us_gaap_like", start_date: "2025-03-01", end_date: "2025-03-31", as_of_date: "2025-03-31", currency: "SGD" }) })); v1.unmount();

  api.mockClear(); setTestUrl("/reports?tab=package&period=1M&end=2025-02-30");
  const v2 = render(React.createElement(Page)); await pkgFw(); await fBtn(/Generate Snapshot/i);
  const cur = readFilters(new URLSearchParams("period=1M"));
  evReqs(api, "/api/reports/package?").forEach((p) => { expDates(p, cur.endDate, cur.startDate); expect(p).not.toContain("2025-02-30"); });
  expect(screen.queryByLabelText("Package report date")).toBeNull(); v2.unmount();

  const monthly = pkgMonthlySnap();
  api.mockImplementation(createPackageRouter(makeReadiness(), defaultPolicy, defaultAppendix, defaultLineage, [monthly], monthly) as never);
  setTestUrl("/reports?tab=package&start=2025-03-01&end=2025-03-31");
  render(React.createElement(Page)); await pkgFw(); await fBtn(/Generate Snapshot/i); api.mockClear();
  fireEvent.change(lbl("Period start"), { target: { value: "2025-03-02" } });
  await waitFor(() => expect(evReqs(api, "/api/reports/package?").some((p) => p.includes("start_date=2025-03-02"))).toBe(true));
  expDates(evReqs(api, "/api/reports/package?")[0], "2025-03-31", "2025-03-02");
  api.mockClear(); clk("Reopen"); await see("Frozen snapshot snap-001");
  const cov = within(reg("Report package cover"));
  expect(cov.getByText("2025-03-01 to 2025-03-31")).toBeInTheDocument();
  expect(cov.getByText("Balances as of").nextElementSibling).toHaveTextContent("2025-04-01");
  expect(evReqs(api, "/api/reports/package?")).toEqual([]);
  act(() => setTestUrl("/reports?tab=package&start=2025-04-01&end=2025-04-30"));
  await waitFor(() => noTxt("Frozen snapshot snap-001"));
  await waitFor(() => expect(evReqs(api, "/api/reports/package?").some((p) => p.includes("start_date=2025-04-01"))).toBe(true));
}
export async function assertPkgLoadUnmountAbortPrint(api: AnyMock & { mockRejectedValueOnce: (e: unknown) => unknown }, Page: React.ComponentType) {
  api.mockRejectedValueOnce(new Error("package document unavailable"));
  const v1 = render(React.createElement(Page)); expect(txt("Loading package document...")).toBeInTheDocument(); await see("package document unavailable"); v1.unmount();
  api.mockImplementation(((p: string) => (p.startsWith("/api/reports/package?") ? Promise.reject(new Error("Document unavailable")) : Promise.resolve([]))) as never);
  const v2 = render(React.createElement(Page)); await see("Document unavailable"); v2.unmount();
  let res!: (v: ReturnType<typeof makePackagePreview>) => void;
  api.mockImplementation(((p: string) => (p.startsWith("/api/reports/package?") ? new Promise((r) => { res = r; }) : Promise.resolve([]))) as never);
  const v3 = render(React.createElement(Page)); await waitFor(() => expect(typeof res).toBe("function")); v3.unmount(); await act(async () => { res(makePackagePreview()); });
  api.mockImplementation(((p: string) => p.startsWith("/api/reports/package?framework_id=") ? Promise.reject(new Error("Framework package unavailable")) : p.startsWith("/api/reports/package?") ? Promise.resolve(makePackagePreview()) : Promise.resolve([])) as never);
  const v4 = render(React.createElement(Page)); await pkgFw(); await see("Framework package unavailable"); v4.unmount();
  api.mockImplementation(((p: string) => p.startsWith("/api/reports/package?framework_id=") ? Promise.reject(new DOMException("Canceled", "AbortError")) : p.startsWith("/api/reports/package?") ? Promise.resolve(makePackagePreview()) : p === "/api/reports/package/snapshots" ? Promise.resolve([]) : p.startsWith("/api/reports/coverage?") ? Promise.resolve({ as_of_date: "2026-05-20", coverage_start: null }) : new Promise(() => undefined)) as never);
  const v5 = render(React.createElement(Page)); await pkgFw();
  await waitFor(() => expect(screen.queryByText("Failed to load package data.")).not.toBeInTheDocument());
  assertSkeletonLoading(v5.container, "Loading report package"); v5.unmount();
  api.mockImplementation(createPackageRouter() as never); const pm = vi.fn(), op = window.print; window.print = pm;
  try { render(React.createElement(Page)); await pkgFw(); await fClk(/Print \/ Save as PDF/i); expect(pm).toHaveBeenCalled(); } finally { window.print = op; }
}
export async function assertPkgGateTocLeapScope(api: AnyMock & { mock: { calls: unknown[][] } }, Page: React.ComponentType) {
  const base = createPackageRouter();
  api.mockImplementation(((p: string, o?: RequestInit) => (p.startsWith("/api/reports/package?") ? Promise.resolve({ ...makePackagePreview(), context: { ...makePackagePreview().context, include_restricted: false } }) : base(p, o))) as never);
  const v1 = render(React.createElement(Page));
  await see("Select a framework before package output is loaded.");
  expect(reg("Package setup guidance")).toBeInTheDocument();
  expect(lnk("Reporting Framework", screen.getByRole("navigation", { name: "Report package table of contents" }))).toHaveAttribute("href", "#package-framework-selection");
  expect(evReqs(api, "/api/reports/package?").some((p) => p.includes("framework_id="))).toBe(false);
  await pkgFw();
  expect(txt("Liquid net worth", (await fHdg("Balance Sheet", 2)).closest("section")!)).toBeInTheDocument();
  for (const r of ["/readiness", "/framework-policy", "/annualized-income-schedule", "/traceability"]) expect(api.mock.calls.some(([p]) => String(p).includes(r))).toBe(false);
  noAll(["framework_selection", "report_readiness", "source_trust_summary", "framework_policy_result"]);
  pkgClosedAudit("policy-result:personal_us_gaap_like:2025-05-20:2026-05-20:fixture");
  clkTxt("Reporting basis audit details"); await see("assets.marketable_securities"); v1.unmount();

  api.mockImplementation(createPackageRouter() as never); setTestUrl("/reports?tab=package&period=1M&end=2024-02-29");
  render(React.createElement(Page)); await pkgFw(); await fHdg("Reporting Basis");
  const dated = (e: string) => api.mock.calls.map(([p]) => String(p)).filter((p) => p.includes(`end_date=${e}`));
  expDates(dated("2024-02-29")[0], "2024-02-29", "2024-02-01");
  clk("Previous period"); await waitFor(() => expect(dated("2024-01-31").length).toBeGreaterThan(0)); expDates(dated("2024-01-31")[0], "2024-01-31", "2024-01-01");
  clk("Next period"); clk("Next period"); await waitFor(() => expect(dated("2024-03-31").length).toBeGreaterThan(0)); expDates(dated("2024-03-31")[0], "2024-03-31", "2024-03-01");
  act(() => setTestUrl("/reports?tab=package&end=2026-04-30")); await waitFor(() => expect(dated("2026-04-30")).toHaveLength(1)); expDates(dated("2026-04-30")[0], "2026-04-30", "2025-05-01");
  const toc = screen.getByRole("navigation", { name: "Report package table of contents" });
  for (const [l, h] of [["Report Readiness", "#package-readiness"], ["Authority Coverage", "#package-input-manifest"], ["Reporting Basis", "#package-framework-policy"], ["Balance Sheet ready", "#package-section-balance_sheet"], ["Traceability Summary", "#package-traceability-detail"]] as const) expect(lnk(l, toc)).toHaveAttribute("href", h);
}
export async function assertPkgSnapshotsExports(api: AnyMock, dl: AnyMock & { mockResolvedValue: (v: unknown) => unknown; mockRejectedValueOnce: (e: unknown) => unknown }, track: unknown, eventName: string, Page: React.ComponentType) {
  const restore = stubBlobUrl();
  try {
    dl.mockResolvedValue({ blob: new Blob(["ok"], { type: "text/csv" }), filename: "p.csv" });
    api.mockImplementation(createPackageRouter() as never);
    const v1 = render(React.createElement(Page)); await pkgFw();
    await fClk("Download JSON snapshot snap-001 for US-like 2025-05-20 to 2026-05-20"); await wfCall(dl, "/api/reports/package/snapshots/snap-001/exports?format=json");
    clk("Download CSV snapshot snap-001 for US-like 2025-05-20 to 2026-05-20"); await wfCall(dl, "/api/reports/package/snapshots/snap-001/exports?format=csv");
    clk(/Generate Snapshot/i); await see("Frozen snapshot snap-001"); expect(await fHdg("Recent Snapshots")).toBeInTheDocument();
    await wfCall(vi.mocked(track as () => unknown), eventName, expect.objectContaining({ framework_id: "personal_us_gaap_like" })); v1.unmount();

    vi.mocked(track as () => unknown).mockReset();
    api.mockImplementation(createPackageRouter(makeReadiness(), defaultPolicy, defaultAppendix, defaultLineage, [defaultSnapshot], new Error("Snapshot generation failed")) as never);
    const v2 = render(React.createElement(Page)); await pkgFw(); await fClk(/Generate Snapshot/i); await see("Snapshot generation failed");
    expect(vi.mocked(track as () => unknown)).not.toHaveBeenCalledWith(eventName, expect.anything());
    dl.mockRejectedValueOnce(new Error("Snapshot download failed")); clk("Download CSV snapshot snap-001 for US-like 2025-05-20 to 2026-05-20"); await see("Snapshot download failed"); v2.unmount();

    api.mockImplementation(createPackageRouter(makeReadiness(), defaultPolicy, defaultAppendix, defaultLineage, [{ ...defaultSnapshot, id: "s1", created_at: null }, { ...defaultSnapshot, id: "s2", created_at: "bad-date" }]) as never);
    render(React.createElement(Page)); await pkgFw(); await see("Not recorded"); expect(txt("bad-date")).toBeInTheDocument();
  } finally { restore(); }
}
export async function assertPkgHkAbortGuard(api: AnyMock, Page: React.ComponentType) {
  const sigs: AbortSignal[] = [], res: Array<() => void> = [], hk = pkgHkPolicy();
  api.mockImplementation(((p: string, o?: RequestInit) => {
    if (p.startsWith("/api/reports/package?") && !p.includes("framework_id=")) return Promise.resolve(makePackagePreview());
    if (p === "/api/reports/package/snapshots") return Promise.resolve([defaultSnapshot]);
    if (p.startsWith("/api/reports/package?framework_id=personal_us_gaap_like")) { if (o?.signal) sigs.push(o.signal); return new Promise((r) => { res.push(() => r(makePackagePreview())); }); }
    if (p.startsWith("/api/reports/package?framework_id=personal_hkfrs_like")) return Promise.resolve(makePackagePreview(makeReadiness(), hk));
    return Promise.reject(new Error(`Unexpected ${p}`));
  }) as never);
  render(React.createElement(Page)); await pkgFw("US-like"); await waitFor(() => expect(sigs.length).toBeGreaterThan(0)); await pkgFw("HK-like");
  await waitFor(() => expect(sigs.every((s) => s.aborted)).toBe(true));
  expect((await fAllTxt("policy-result:personal_hkfrs_like:2025-05-20:2026-05-20:fixture")).length).toBeGreaterThanOrEqual(1);
  expect(txt("HK-like selected for this package.")).toBeInTheDocument();
  pkgClosedAudit("personal_hkfrs_like"); pkgClosedAudit("none");
  await act(async () => { res.forEach((r) => r()); });
  expect(screen.queryByText("policy-result:personal_us_gaap_like:2025-05-20:2026-05-20:fixture")).not.toBeInTheDocument();
}
export async function assertPkgSectionsAndAudit(api: AnyMock, Page: React.ComponentType) {
  api.mockImplementation(createPackageRouter() as never); const v1 = render(React.createElement(Page)); await pkgFw();
  expect((await fHdg("Report Readiness")).compareDocumentPosition(hdg("Balance Sheet")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(hdg("Authority Coverage").compareDocumentPosition(hdg("Traceability Summary")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  hasAny(["2 blockers must be resolved before package output is trusted.", "Pending source review", "1 decisions", "SGD 100,000", "SGD 22,500", "ACME", "SHOP-RSU", "SGD 12,500", "exclude_restricted_holdings", "Basis of Preparation", "Valuation Basis", "manual_valuation_snapshots", "json, csv", "string", "4 evidence anchors", "Salary"]);
  expect(txt("Export audit details").closest("details")).toHaveClass("print:hidden");
  for (const a of ["Framework Policy Result", "unsupported_policy_domain", "pending_review", "balance_sheet.total_assets", "static_contract_note", "manual_only_source"]) pkgClosedAudit(a);
  for (const sum of ["Readiness audit details", "Authority manifest audit details", "Reporting basis audit details", "Traceability audit details", "Export audit details"]) {
    const d = txt(sum).closest("details"); expect(d).not.toHaveAttribute("open"); clkTxt(sum); expect(d).toHaveAttribute("open");
  }
  await see(new RegExp(`${PKG_IDS.decision} journal_command:statement-transaction:${PKG_IDS.stmt}@fixture-v1`)); v1.unmount();
  api.mockImplementation(createPackageRouter(makeReadiness({ state: "generated", label: "Generated", blocking_count: 0, blockers: [] }), pkgOtherPolicy(), { ...defaultAppendix, status: "pending_review" }) as never);
  render(React.createElement(Page)); await pkgFw(); await see("Current package state is generated.");
  const basis = hdg("Reporting Basis").closest("section")!;
  expect(allTxt("Personal Income", basis)).toHaveLength(1); expect(txt("3 items", basis)).toBeInTheDocument();
  expect(txt("Pending Review", txt("Manual Private Asset").closest("article")!)).toBeInTheDocument();
  expect(within(hdg("Traceability Summary").closest("section")!).queryByText("pending_review")).not.toBeInTheDocument();
}
type ApiCalls = AnyMock & { mock: { calls: unknown[][] }; mockClear: () => void; mockReset: () => void };
export async function assertPkgLazyDetailsManifest(api: ApiCalls, Page: React.ComponentType) {
  api.mockImplementation(createPackageRouter() as never); const v1 = render(React.createElement(Page)); await pkgFw(); await fHdg("Traceability Summary");
  expect(evReqs(api, "/api/reports/package/line-details?")).toEqual([]); expect(evReqs(api, "/api/reports/package/manifest-entries?")).toEqual([]);
  clk("Reopen"); await see("Frozen snapshot snap-001"); clk("Show evidence details for Total Assets");
  await see(`statement_transaction:${PKG_IDS.stmt}`); expect(txt(`journal_line:${PKG_IDS.line}`)).toBeInTheDocument();
  clkTxt("Authority manifest audit details"); await see(new RegExp(`${PKG_IDS.decision} journal_command`));
  expect(evReqs(api, "/api/reports/package/line-details?")).toEqual([]); expect(evReqs(api, "/api/reports/package/manifest-entries?")).toEqual([]); v1.unmount();

  const lids = Array.from({ length: 210 }, (_u, i) => `journal_line:00000000-0000-4000-8000-${String(i).padStart(12, "0")}`);
  const r210 = createPackageRouter(makeReadiness(), defaultPolicy, { ...defaultAppendix, lines: [{ ...defaultAppendix.lines[0], ledger_anchor: withIds(defaultAppendix.lines[0].ledger_anchor, lids) }] });
  api.mockImplementation(((p: string, o?: RequestInit) => (p.startsWith("/api/reports/package/line-details?") && p.includes("anchor=source_anchor") ? Promise.reject(new Error("Source evidence unavailable")) : r210(p, o))) as never);
  const v2 = render(React.createElement(Page)); await pkgFw(); await fClk("Show evidence details for Total Assets");
  const ledger = await fReg("Ledger evidence for Total Assets");
  await see(lids[199], ledger); expect(ledger).toHaveTextContent("Ledger evidence: 200 of 210 details"); await see("Source evidence unavailable");
  clk("Load more ledger evidence", ledger); await see(lids[209], ledger);
  clk("Trace evidence for Total Assets"); await wfCall(api, expect.stringContaining("/api/statements/evidence-lineage?entity_type=journal_line"));
  expect(evReqs(api, "/api/reports/package/line-details?").filter((p) => p.includes("anchor=ledger_anchor"))).toHaveLength(2);
  clk("Hide evidence details for Total Assets"); expect(screen.queryByText(lids[0])).not.toBeInTheDocument(); v2.unmount();

  const entries = Array.from({ length: 201 }, (_u, i) => ({ ...makePackageDoc().input_manifest[0], decision_id: `77777777-7777-4777-8777-${String(i).padStart(12, "0")}` }));
  const rBase = createPackageRouter();
  api.mockImplementation(((p: string, o?: RequestInit) => { if (!p.startsWith("/api/reports/package/manifest-entries?")) return rBase(p, o); const off = Number(new URL(p, "http://x").searchParams.get("offset")); return Promise.resolve({ total: 201, limit: 200, offset: off, entries: entries.slice(off, off + 200) }); }) as never);
  const v3 = render(React.createElement(Page)); await pkgFw(); await fClkTxt("Authority manifest audit details");
  await see(new RegExp(entries[199].decision_id)); clk("Load more decisions"); await see(new RegExp(entries[200].decision_id)); v3.unmount();

  api.mockImplementation(((p: string, o?: RequestInit) => (p.startsWith("/api/reports/package/manifest-entries?") || p.startsWith("/api/reports/package/line-details?") ? Promise.reject(new Error("Evidence page unavailable")) : rBase(p, o))) as never);
  const v4 = render(React.createElement(Page)); await pkgFw(); await fClkTxt("Authority manifest audit details"); await see("Evidence page unavailable");
  clk("Trace evidence for Total Assets"); await see("Evidence page unavailable", await fDlg("Evidence Lineage")); v4.unmount();

  api.mockClear(); api.mockImplementation(createPackageRouter(makeReadiness({ input_coverage: { manifest_decision_count: 0, authoritative_input_count: 0, unproven_input_count: 0 } }), defaultPolicy, { ...defaultAppendix, lines: [defaultAppendix.lines[0], { ...defaultAppendix.lines[1], source_anchor: withIds(defaultAppendix.lines[1].source_anchor, []) }] }) as never);
  render(React.createElement(Page)); await pkgFw(); await fClkTxt("Authority manifest audit details"); await see("No authority decisions are pinned for this document.");
  clk("Show evidence details for Package Non-Compliance Statement"); await see("This line has no evidence details.");
  expect(evReqs(api, "/api/reports/package/manifest-entries?")).toEqual([]); expect(evReqs(api, "/api/reports/package/line-details?")).toEqual([]);
}
export async function assertPkgLineageAndMapping(api: ApiCalls, Page: React.ComponentType) {
  api.mockImplementation(createPackageRouter() as never); const v1 = render(React.createElement(Page)); await pkgFw(); await fClk("Trace evidence for Total Assets");
  await fDlg("Evidence Lineage"); await wfCall(api, `/api/statements/evidence-lineage?entity_type=journal_line&entity_id=${PKG_IDS.line}&node_kind=ledger_line&direction=both&max_depth=6`);
  for (const s of ["source_document", "extracted_record", "atomic_fact", "ledger_entry", "ledger_line", "report_line", "parsed_into", "aggregated_into", `uploaded_document:${PKG_IDS.doc}`]) await see(s);
  clk("Close evidence lineage"); await waitFor(() => expect(screen.queryByRole("dialog", { name: "Evidence Lineage" })).not.toBeInTheDocument()); v1.unmount();

  for (const [app, lin, msg] of [
    [{ ...defaultAppendix, lines: [{ ...defaultAppendix.lines[0], ledger_anchor: withIds(defaultAppendix.lines[0].ledger_anchor, ["journal_line:not-a-uuid"]), source_anchor: withIds(defaultAppendix.lines[0].source_anchor, []) }] }, defaultLineage, "lineage_anchor_missing"],
    [defaultAppendix, new Error("lineage unavailable"), "lineage unavailable"],
  ] as const) {
    api.mockImplementation(createPackageRouter(makeReadiness(), defaultPolicy, app, lin) as never);
    const v = render(React.createElement(Page)); await pkgFw(); await fClk("Trace evidence for Total Assets"); await see(msg); v.unmount();
  }
  for (const [id, et, eid, nk] of [[`uploaded_document:${PKG_IDS.doc}`, "uploaded_document", PKG_IDS.doc, "source_document"], [`statement_transaction:${PKG_IDS.stmt}`, "bank_statement_transaction", PKG_IDS.stmt, "extracted_record"], [`atomic_transaction:${PKG_IDS.atomic}`, "atomic_transaction", PKG_IDS.atomic, "atomic_fact"]] as const) {
    api.mockReset(); api.mockImplementation(createPackageRouter(makeReadiness(), defaultPolicy, { ...defaultAppendix, lines: [{ ...defaultAppendix.lines[0], ledger_anchor: withIds(defaultAppendix.lines[0].ledger_anchor, []), source_anchor: withIds(defaultAppendix.lines[0].source_anchor, [id]) }] }) as never);
    const v = render(React.createElement(Page)); await pkgFw(); await fClk("Trace evidence for Total Assets");
    await wfCall(api, `/api/statements/evidence-lineage?entity_type=${et}&entity_id=${eid}&node_kind=${nk}&direction=both&max_depth=6`);
    expect(evReqs(api, "/api/reports/package/line-details?")).toEqual([expect.stringContaining("anchor=source_anchor")]); v.unmount();
  }
}
export async function assertPkgPolicyPaging(api: ApiCalls, Page: React.ComponentType) {
  const p30 = { ...defaultPolicy, decisions: pkgManyDec(30) };
  api.mockImplementation(createPackageRouter(makeReadiness(), p30) as never); const v1 = render(React.createElement(Page)); await pkgFw(); await fHdg("Reporting Basis");
  expect(txt("Showing 25 of 30 decisions. The reporting basis audit details list all of them.")).toBeInTheDocument();
  expect(txt(/and 5 more in the snapshot export/)).toBeInTheDocument();
  expect(evReqs(api, "/api/reports/package/policy-decisions?")).toEqual([]);
  clkTxt("Reporting basis audit details"); await see("assets.line_29"); expect(txt("Policy decisions: 30 of 30")).toBeInTheDocument(); v1.unmount();

  api.mockImplementation(createPackageRouter(makeReadiness(), { ...defaultPolicy, decisions: pkgManyDec(201) }) as never);
  const v2 = render(React.createElement(Page)); await pkgFw(); await fClkTxt("Reporting basis audit details");
  const list = await fReg("Policy decisions"); await see("assets.line_199", list);
  clk("Load more policy decisions", list); await see("assets.line_200", list); expect(list).toHaveTextContent("Policy decisions: 201 of 201"); v2.unmount();

  const b = createPackageRouter(makeReadiness(), p30);
  api.mockImplementation(((p: string, o?: RequestInit) => (p.startsWith("/api/reports/package/policy-decisions?") ? Promise.reject(new Error("Decisions unavailable")) : b(p, o))) as never);
  const v3 = render(React.createElement(Page)); await pkgFw(); await fClkTxt("Reporting basis audit details"); await see("Decisions unavailable"); v3.unmount();

  api.mockImplementation(createPackageRouter(makeReadiness(), { ...defaultPolicy, decisions: [{ ...defaultPolicy.decisions[0], evidence_anchors: [] }] }) as never);
  const v4 = render(React.createElement(Page)); await pkgFw(); await fClkTxt("Reporting basis audit details"); await see("Policy decisions: 1 of 1"); v4.unmount();

  api.mockClear(); api.mockImplementation(createPackageRouter(makeReadiness(), { ...defaultPolicy, decisions: [] }) as never);
  const v5 = render(React.createElement(Page)); await pkgFw(); await fClkTxt("Reporting basis audit details");
  expect(screen.queryByRole("region", { name: "Policy decisions" })).not.toBeInTheDocument(); expect(evReqs(api, "/api/reports/package/policy-decisions?")).toEqual([]); v5.unmount();

  const snap = { ...defaultSnapshot, document: makePackageDoc(makeReadiness(), p30, defaultAppendix, "frozen", "snap-001") };
  api.mockImplementation(createPackageRouter(makeReadiness(), p30, defaultAppendix, defaultLineage, [snap], snap) as never);
  render(React.createElement(Page)); await pkgFw(); await fClk("Reopen"); await see("Frozen snapshot snap-001");
  clkTxt("Reporting basis audit details"); await see("assets.line_29"); expect(evReqs(api, "/api/reports/package/policy-decisions?")).toEqual([]);
}
export async function assertPkgSharedCacheAndHold(api: ApiCalls, pkgQuery: (a: never) => { queryKey: readonly unknown[] }, readFilters: (p: URLSearchParams) => { startDate: string; endDate: string }, Page: React.ComponentType) {
  api.mockImplementation(createPackageRouter() as never); const { w: w1 } = qcWrap(); setTestUrl("/reports");
  const hub = render(React.createElement(Page), w1); await fLbl("Report readiness cockpit");
  await waitFor(() => expect(evReqs(api, "/api/reports/package?")).toHaveLength(1));
  await waitFor(() => noTxt("Checking")); hub.unmount();
  setTestUrl("/reports?tab=package"); const p1 = render(React.createElement(Page), w1); await pkgFw(); await fBtn(/Generate Snapshot/i); p1.unmount();
  api.mockClear(); const p2 = render(React.createElement(Page), w1); await pkgFw(); await fBtn(/Generate Snapshot/i);
  expect(evReqs(api, "/api/reports/package?")).toEqual([]); p2.unmount();

  const s = createPackageRouter(); api.mockImplementation(s as never); const { w: w2 } = qcWrap();
  const v2 = render(React.createElement(Page), w2); await pkgFw(); await fBtn(/Generate Snapshot/i);
  let rel!: () => void; api.mockImplementation(((p: string, o?: RequestInit) => (p.startsWith("/api/reports/package?") ? new Promise((r) => { rel = () => r(makePackagePreview()); }) : s(p, o))) as never);
  act(() => setTestUrl("/reports?tab=package&end=2025-03-31"));
  expect(await fTxt(/The report below still shows/)).toHaveTextContent("Loading the package for 2024-04-01 to 2025-03-31. The report below still shows 2025-05-20 to 2026-05-20");
  dis(/Generate Snapshot/i); await act(async () => { rel(); }); await waitFor(() => expect(screen.queryByText(/The report below still shows/)).not.toBeInTheDocument());
  api.mockImplementation(((p: string, o?: RequestInit) => (p.startsWith("/api/reports/package?framework_id=personal_hkfrs_like") ? new Promise(() => {}) : s(p, o))) as never);
  clk("HK-like"); await screen.findByRole("status", { name: "Loading report package" });
  expect(screen.queryByRole("heading", { name: "Reporting Basis" })).not.toBeInTheDocument(); v2.unmount();

  api.mockImplementation(s as never); const { c: c3, w: w3 } = qcWrap(); setTestUrl("/reports?tab=package");
  render(React.createElement(Page), w3); await pkgFw(); await fClk(/Generate Snapshot/i); await see("Frozen snapshot snap-001");
  expect(api.mock.calls.filter(([p]) => p === "/api/reports/package/snapshots").length).toBeGreaterThanOrEqual(2);
  const cur = readFilters(new URLSearchParams());
  expect(c3.getQueryState(pkgQuery({ frameworkId: "personal_us_gaap_like", reportDate: cur.endDate, startDate: cur.startDate } as never).queryKey)?.isInvalidated).toBe(true);
}
export function assertPkgSectionCardsScope(Cards: React.ComponentType<{ sections: never; includeRestricted?: boolean }>) {
  const { sec, bal, oldBal } = pkgScopeSections();
  const v1 = render(React.createElement(Cards, { sections: { ...sec, cash_flow: { ...sec.cash_flow, cash_bridge: { opening_stock_adjustment: "100", reconciles: true }, proof_state: "unproven", proof_reasons: ["opening_coverage_starts_after_period"] } } as never }));
  expect(txt("Known Beginning Cash")).toBeInTheDocument(); expect(txt(/records start after the selected period begins/i)).toBeInTheDocument(); v1.unmount();
  const v2 = render(React.createElement(Cards, { sections: { ...sec, balance_sheet: bal } as never, includeRestricted: false }));
  expect(txt("Liquid net worth").nextElementSibling).toHaveTextContent("SGD 20,361");
  expect(tid("excluded-holdings-note")).toHaveTextContent("Excludes restricted and illiquid holdings:Real Estate SGD 550,000 (net of SGD 650,000 liabilities)Restricted Comp SGD 42,000"); v2.unmount();
  const noRows = { ...sec, balance_sheet: { ...bal, excluded_holdings: [] } } as never;
  const v3 = render(React.createElement(Cards, { sections: noRows, includeRestricted: false })); expect(screen.queryByTestId("excluded-holdings-note")).toBeNull(); v3.unmount();
  const v4 = render(React.createElement(Cards, { sections: noRows, includeRestricted: true })); expect(txt("Net worth").nextElementSibling).toHaveTextContent("SGD 20,361"); v4.unmount();
  const v5 = render(React.createElement(Cards, { sections: { ...sec, balance_sheet: { ...oldBal, currency: "SGD", total_assets: "20360.65", total_liabilities: "650000.00" } } as never }));
  noTxt("Net worth"); expect(txt("This snapshot does not record its restricted-holdings scope, so no net worth is shown.")).toBeInTheDocument(); v5.unmount();
  render(React.createElement(Cards, { sections: { ...sec, investment_performance: { ...sec.investment_performance, holdings: [] }, cash_flow: { ...sec.cash_flow, proof_state: "unproven", proof_reasons: ["opening_position_unproven"] } } as never }));
  expect(txt(/opening balance evidence needs review/i)).toBeInTheDocument(); noTxt("Opening balance adjustment");
}

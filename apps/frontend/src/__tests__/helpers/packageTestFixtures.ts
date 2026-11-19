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
export const PKG_IDS = { stmt: u("1"), entry: u("2"), line: u("3"), doc: u("4"), atomic: u("5"), reportLine: u("6"), decision: u("7") };
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

export const makeReadiness = (o: Record<string, unknown> = {}) => ({
  package_id: P_ID, state: "blocked", label: "Blocked", action_href: "/review", blocking_count: 2,
  input_coverage: { manifest_decision_count: 1, authoritative_input_count: 4, unproven_input_count: 2 },
  blockers: [{ code: "pending_review", label: "Pending source review", severity: "blocking", count: 1, reason: "R", action_href: "/review" }, { code: "balance_mismatch", label: "Balance validation mismatch", severity: "blocking", count: 1, reason: "M", action_href: "/review" }],
  generated_at: null, stale_since: null, ...o,
});
export const makeBalanceSheet = (o: Record<string, unknown> = {}) => ({ as_of_date: D1, currency: "SGD", assets: [], liabilities: [], equity: [], total_assets: "100000.00", total_liabilities: "35000.00", total_equity: "65000.00", net_income: "25400.00", unrealized_fx_gain_loss: "0.00", net_worth_adjustment_gain_loss: "0.00", equation_delta: "0.00", is_balanced: true, ...o });
export const makeIncomeStatement = (o: Record<string, unknown> = {}) => ({ start_date: D0, end_date: D1, currency: "SGD", income: [], expenses: [], total_income: "137400.00", total_expenses: "112000.00", net_income: "25400.00", trends: [], ...o });
export const makeCashFlow = (o: Record<string, unknown> = {}) => ({ start_date: D0, end_date: D1, currency: "SGD", operating: [], investing: [], financing: [], summary: { operating_activities: "31000.00", investing_activities: "-6000.00", financing_activities: "-2500.00", net_cash_flow: "22500.00", beginning_cash: "30000.00", ending_cash: "52500.00" }, ...o });
export const makeHolding = (o: Partial<PortfolioHolding> = {}): PortfolioHolding => ({ id: "h1", user_id: "u1", account_id: "acc1", asset_identifier: "AAPL", quantity: "10", cost_basis: "1500.00", market_value: "1800.00", unrealized_pnl: "300.00", unrealized_pnl_percent: "20.00", currency: "USD", native_cost_basis: o.cost_basis ?? "1500.00", native_currency: o.currency ?? "USD", reporting_cost_basis: o.cost_basis ?? "1500.00", reporting_currency: o.currency ?? "USD", acquisition_date: "2025-01-15", status: "active", account_name: "IBKR", asset_type: "Equity", sector: "Technology", geography: "US", ...o });
export const makeSchedule = (o: Record<string, unknown> = {}): InvestmentPerformanceReportSchedule => ({
  period_start: "2026-01-01", period_end: "2026-03-31", as_of_date: "2026-04-01", currency: "SGD", xirr: "8.25", time_weighted_return: "5.00", money_weighted_return: "4.00", dividend_yield: "1.50", realized_pnl: "1200.00", unrealized_pnl: "300.00", dividend_income: "88.00",
  holdings: [{ asset_identifier: "AAPL", quantity: "10", cost_basis: "1000.00", market_value: "1200.00", unrealized_pnl: "200.00", realized_pnl: "0.00", dividend_income: "0.00", currency: "SGD" }, { asset_identifier: "MSFT", quantity: "5", cost_basis: "2000.00", market_value: "2100.00", unrealized_pnl: "100.00", realized_pnl: "0.00", dividend_income: "0.00", currency: "SGD" }],
  allocation: [], data_freshness: { latest_price_date: "2026-04-01", market_data_provider: "IBKR", stale: false, stale_holdings: [], manual_override_basis: null }, source_links: [], notes: [], ...o,
}) as InvestmentPerformanceReportSchedule;
export const withIds = <T extends { identifiers: string[] }>(a: T, ids: string[]) => ({
  ...a, identifiers: ids,
  details: ids.map((id) => ({ identifier: id, source_kind: id.split(":")[0], source_id: id.slice(id.indexOf(":") + 1), amount: id.startsWith("journal_line:") ? "120.00" : null, currency: id.startsWith("journal_line:") ? "SGD" : null, review_state: "current_authoritative_decision", decision_id: PKG_IDS.decision, reason_code: null })),
});
export const defaultPolicy = {
  result_id: `policy-result:personal_us_gaap_like:${D0}:${D1}:fixture`, framework_id: "personal_us_gaap_like", matrix_version: "1.0", report_period_start: D0, report_period_end: D1, generated_at: D1, required_statements: ["balance_sheet"],
  decisions: [{ domain: "listed_security", recognition: "O", measurement: "Q", classification: "Marketable investment asset.", presentation: "US", disclosure: "P", line_mappings: { balance_sheet: "assets.marketable_securities" }, evidence_anchors: [{ anchor_id: "atomic_position:abc", anchor_type: "atomic_position", source_system: "atomic_positions", source_id: "abc", description: "H" }], provenance: "deterministic_matrix", review_state: "accepted", policy_field_name: "framework_policy_decision", accepted_value: "listed_security" }],
  gaps: [{ code: "unsupported_policy_domain", fact_id: "atomic_position:private-token", domain: "unsupported", instrument_type: "other", blocker: true, reason: "N", remediation: "A", evidence_anchors: [{ anchor_id: "atomic_position:private-token", anchor_type: "atomic_position", source_system: "atomic_positions", source_id: "private-token", description: "T" }] }],
};
const anc = (s: string, k: string, t: string[], ids: string[]) => withIds({ state: s, [k]: t, identifier_fields: ["ids"], identifiers: [] as string[] }, ids);
export const defaultAppendix = {
  section_id: "traceability_appendix", label: "Traceability Appendix", status: "ready",
  lines: [
    { line_id: "balance_sheet.total_assets", section_id: "balance_sheet", label: "Total Assets", amount_field: "total_assets", currency_field: "currency", source_state: "posted_reconciled_journal_lines_and_manual_valuations", source_anchor: anc("available", "source_types", ["bank_statement", "manual_valuation_snapshot"], [`statement_transaction:${PKG_IDS.stmt}`, "manual_valuation_snapshot:val-456"]), ledger_anchor: anc("available", "entry_statuses", ["posted", "reconciled"], [`journal_entry:${PKG_IDS.entry}`, `journal_line:${PKG_IDS.line}`]), anchor_count: 4, blocker_codes: [] },
    { line_id: "notes.non_compliance_statement", section_id: "notes", label: "Package Non-Compliance Statement", amount_field: null, currency_field: null, source_state: "package_contract", source_anchor: anc("available", "source_types", ["package_contract"], ["note:basis-of-preparation"]), ledger_anchor: anc("not_applicable", "entry_statuses", [], []), anchor_count: 1, blocker_codes: ["static_contract_note"] },
  ],
  completeness_warnings: [{ code: "manual_only_source", label: "Manual-only source coverage", applies_to_sections: ["balance_sheet"], state: "explicit_manual_input_required" }],
};
export function makePackageDoc(r = makeReadiness(), p = defaultPolicy, t: unknown = defaultAppendix, lifecycle: "preview" | "frozen" = "preview", snapshotId: string | null = null) {
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
export function makePackagePreview(r = makeReadiness(), p = defaultPolicy, t: unknown = defaultAppendix) {
  const { snapshot_id: _s, package_decision_id: _d, frozen_at: _f, input_manifest: _m, ...prev } = makePackageDoc(r, p, t);
  const { operating: _o, investing: _i, financing: _fi, ...cf } = prev.sections.cash_flow;
  const full = t as { lines: Array<Record<string, unknown>> };
  const pa = (a: Record<string, unknown>) => { const { identifiers: _ids, details, ...s } = a; return { ...s, detail_count: Array.isArray(details) ? details.length : 0 }; };
  const anchors = [...p.decisions, ...p.gaps].flatMap((i) => i.evidence_anchors ?? []);
  return { ...prev, status: "draft", framework_policy: { ...p, decision_count: p.decisions.length, evidence_reference_count: new Set(anchors.map((a) => `${a.anchor_type}:${a.source_id}`)).size, decisions: p.decisions.slice(0, 25) }, sections: { ...prev.sections, cash_flow: { ...cf, operating: [], investing: [], financing: [], lineage_summary: { event_count: 0, classified_event_count: 0, unclassified_event_count: 0, opening_stock_event_count: 0 } }, traceability_appendix: { ...full, lines: full.lines.map((l) => ({ ...l, source_anchor: pa(l.source_anchor as Record<string, unknown>), ledger_anchor: pa(l.ledger_anchor as Record<string, unknown>) })) } } };
}
export const defaultSnapshot = { id: "snap-001", package_id: P_ID, status: "trusted", framework_id: "personal_us_gaap_like", start_date: D0, end_date: D1, as_of_date: D1, currency: "SGD", readiness_state: "ready", is_latest: true, created_at: T1, document: makePackageDoc(makeReadiness({ state: "ready", label: "Ready", blocking_count: 0, blockers: [] }), defaultPolicy, defaultAppendix, "frozen", "snap-001") };
export const defaultLineage = {
  anchor: { id: "n5", node_kind: "ledger_line", entity_type: "journal_line", entity_id: PKG_IDS.line, properties: {} },
  nodes: [["n1", "source_document", "uploaded_document", PKG_IDS.doc], ["n2", "extracted_record", "bank_statement_transaction", PKG_IDS.stmt], ["n3", "atomic_fact", "atomic_transaction", PKG_IDS.atomic], ["n4", "ledger_entry", "journal_entry", PKG_IDS.entry], ["n5", "ledger_line", "journal_line", PKG_IDS.line], ["n6", "report_line", "package_traceability_line", PKG_IDS.reportLine]].map(([id, node_kind, entity_type, entity_id]) => ({ id, node_kind, entity_type, entity_id, properties: {} })),
  edges: [["e1", "parsed_into", "upstream", 4, "n1", "n2"], ["e2", "deduped_into", "upstream", 3, "n2", "n3"], ["e3", "posted_as", "upstream", 2, "n3", "n4"], ["e4", "contains", "upstream", 1, "n4", "n5"], ["e5", "aggregated_into", "downstream", 1, "n5", "n6"]].map(([id, relation, direction, depth, from_node_id, to_node_id]) => ({ id, relation, direction, depth, from_node_id, to_node_id, properties: {} })),
  blockers: [], max_depth: 6,
};
export function createPackageRouter(r = makeReadiness(), p = defaultPolicy, t: unknown = defaultAppendix, lin: unknown = defaultLineage, snaps: unknown[] = [defaultSnapshot], gen: unknown = defaultSnapshot) {
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
export const fClk = async (n: string | RegExp, r?: HTMLElement) => fireEvent.click(await fBtn(n, r));
export const clkTxt = (t: string | RegExp, r?: HTMLElement) => fireEvent.click(q(r).getByText(t));
export const fClkTxt = async (t: string | RegExp, r?: HTMLElement) => fireEvent.click(await q(r).findByText(t));
export const clkLbl = (t: string | RegExp, r?: HTMLElement) => fireEvent.click(q(r).getByLabelText(t));
export const chgLbl = (t: string | RegExp, value: string, r?: HTMLElement) => fireEvent.change(q(r).getByLabelText(t), { target: { value } });
export const qTxt = (t: string | RegExp, r?: HTMLElement) => q(r).queryByText(t);
export const allTxt = (t: string | RegExp, r?: HTMLElement) => q(r).getAllByText(t);
export const fAllTxt = (t: string | RegExp, r?: HTMLElement) => q(r).findAllByText(t);
export const lbl = (t: string | RegExp, r?: HTMLElement) => q(r).getByLabelText(t);
export const fLbl = (t: string | RegExp, r?: HTMLElement) => q(r).findByLabelText(t);
export const reg = (n: string | RegExp, r?: HTMLElement) => q(r).getByRole("region", { name: n });
export const fReg = (n: string | RegExp, r?: HTMLElement) => q(r).findByRole("region", { name: n });
export const lnk = (n: string | RegExp, r?: HTMLElement) => q(r).getByRole("link", { name: n });
export const fLnk = (n: string | RegExp, r?: HTMLElement) => q(r).findByRole("link", { name: n });
export const hdg = (n: string | RegExp, level?: number, r?: HTMLElement) => q(r).getByRole("heading", { name: n, ...(level ? { level } : {}) });
export const fHdg = (n: string | RegExp, level?: number, r?: HTMLElement) => q(r).findByRole("heading", { name: n, ...(level ? { level } : {}) });
export const dlg = (n?: string | RegExp) => screen.getByRole("dialog", n ? { name: n } : undefined);
export const fDlg = (n?: string | RegExp) => screen.findByRole("dialog", n ? { name: n } : undefined);
export const hasAny = (items: (string | RegExp)[], r?: HTMLElement) => { for (const x of items) expect(allTxt(x, r).length).toBeGreaterThanOrEqual(1); };
export const noAll = (items: (string | RegExp)[], r?: HTMLElement) => { for (const x of items) expect(qTxt(x, r)).toBeNull(); };
export const qcWrap = () => {
  const c = new QueryClient({ defaultOptions: { queries: { staleTime: 60_000, retry: false } } });
  return { c, w: { wrapper: ({ children }: { children: ReactNode }) => React.createElement(QueryClientProvider, { client: c }, children) } };
};
export const stubBlobUrl = () => {
  const cu = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:p");
  const ru = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  return () => { cu.mockRestore(); ru.mockRestore(); };
};
export const stubUrlAssign = (val = "blob:cash-flow-export") => vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => val), revokeObjectURL: vi.fn() }));
export const evReqs = (api: { mock: { calls: unknown[][] } }, pfx: string) => api.mock.calls.map(([p]) => String(p)).filter((p) => p.startsWith(pfx));
export const expDates = (p: string, end: string, start: string) => { const sp = new URL(p, "http://x").searchParams; expect([sp.get("start_date"), sp.get("end_date"), sp.get("as_of_date")]).toEqual([start, end, end]); };
export const wfCall = (fn: unknown, ...args: unknown[]) => waitFor(() => expect(fn).toHaveBeenCalledWith(...args));
export const wfLastCall = (fn: unknown, ...args: unknown[]) => waitFor(() => expect(fn).toHaveBeenLastCalledWith(...args));
export const chgPh = (ph: string | RegExp, value: string, r?: HTMLElement) => fireEvent.change(q(r).getByPlaceholderText(ph), { target: { value } });
export const submitForm = (el: HTMLElement) => fireEvent.submit(el.closest("form") as HTMLFormElement);
export const mockSheet = ({ isOpen, title, children, onClose }: { isOpen: boolean; title: string; children: ReactNode; onClose: () => void }) =>
  isOpen ? React.createElement("div", { role: "dialog", "aria-label": title }, React.createElement("button", { onClick: onClose }, `Close ${title}`), children) : null;
export const mockLink = ({ href, children, ...p }: { href: string; children: ReactNode; [k: string]: unknown }) => React.createElement("a", { href, ...p }, children);
export const assertSkeletonLoading = (container: HTMLElement, name: string, min = 10) => {
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

// --- Package page fixtures ---
export const pkgManyDec = (n: number) => Array.from({ length: n }, (_u, i) => ({
  ...defaultPolicy.decisions[0],
  evidence_anchors: [{ anchor_id: `journal_line:line-${i}`, anchor_type: "journal_line", source_system: "canonical_ledger", source_id: `line-${i}`, description: "A" }],
  line_mappings: { ...defaultPolicy.decisions[0].line_mappings, balance_sheet: `assets.line_${i}` },
}));
export const pkgClosedAudit = (x: string | RegExp) => {
  const d = screen.getAllByText(x).map((n) => n.closest("details")).find((c): c is HTMLDetailsElement => c instanceof HTMLDetailsElement && Boolean(within(c).queryByText(/audit details/i)));
  if (!d) throw new Error(`Missing closed audit: ${x}`);
  expect(d).not.toHaveAttribute("open");
};
export const pkgMonthlySnap = () => ({ ...defaultSnapshot, start_date: "2025-03-01", end_date: "2025-03-31", as_of_date: "2025-04-01", document: { ...defaultSnapshot.document, context: { ...defaultSnapshot.document.context, start_date: "2025-03-01", end_date: "2025-03-31", as_of_date: "2025-04-01" } } });
export const pkgHkPolicy = () => ({ ...defaultPolicy, result_id: "policy-result:personal_hkfrs_like:2025-05-20:2026-05-20:fixture", framework_id: "personal_hkfrs_like", decisions: [], gaps: [] });
export const pkgOtherPolicy = () => {
  const other = { ...defaultPolicy.decisions[0], domain: "personal_income" as const, classification: "Other income", line_mappings: { ...defaultPolicy.decisions[0].line_mappings, income_statement: "income.other" } };
  return { ...defaultPolicy, decisions: [{ ...defaultPolicy.decisions[0], domain: "manual_private_asset", classification: "Private asset.", review_state: "pending_review" }, ...[1, 2, 3].map((i) => ({ ...other, evidence_anchors: [{ anchor_id: `journal_line:${i}`, anchor_type: "journal_line", source_system: "canonical_ledger", source_id: String(i), description: "L" }] }))] };
};
export const pkgScopeSections = () => {
  const sec = makePackageDoc().sections;
  const bal = { ...sec.balance_sheet, currency: "SGD", total_assets: "20360.65", total_liabilities: "0.00", excluded_holdings: [{ asset_class: "real_estate", total_assets: "1200000.00", total_liabilities: "650000.00", net_worth: "550000.00", warnings: [] }, { asset_class: "restricted_comp", total_assets: "42000.00", total_liabilities: "0.00", net_worth: "42000.00", warnings: [] }] };
  const { excluded_holdings: _d, ...oldBal } = { ...sec.balance_sheet, excluded_holdings: undefined };
  return { sec, bal, oldBal };
};

// --- Portfolio page fixtures & router ---
export const PORT_H1 = makeHolding();
export const PORT_H2 = makeHolding({ id: "h2", asset_identifier: "TSLA", quantity: "5", cost_basis: "1000.00", market_value: "900.00", unrealized_pnl: "-100.00", unrealized_pnl_percent: "-10.00", disposal_date: "2025-11-01", status: "disposed", sector: "Automotive" });
export type PortAllocMode = "default" | "retirement_benefit" | "empty" | "error" | "pending";
export function mockPortfolioRouter(api: AnyMock, holdings: PortfolioHolding[] = [PORT_H1], allocPct: string | null = "100.00", schedCurr = "USD", mode: PortAllocMode = "default", allowPricePost = false) {
  api.mockImplementation(((path: string) => {
    if (allowPricePost && path === "/api/pricing/price-overrides") return Promise.resolve({ updated_count: 1, errors: [] });
    if (path.startsWith("/api/portfolio/summary")) return Promise.resolve({ total_market_value: "1800.00", total_cost_basis: "1500.00", total_unrealized_pnl: "300.00", total_unrealized_pnl_percent: "20.00", total_realized_pnl: "149.00", total_realized_pnl_percent: "9.93", net_pnl: "449.00", net_pnl_percent: "29.93", holdings_count: holdings.length, active_positions_count: holdings.filter((h) => h.status === "active").length, disposed_positions_count: holdings.filter((h) => h.status === "disposed").length, currency: "SGD", realized_pnl_ytd: "149.00", dividend_income_ytd: "42.50" });
    if (path.startsWith("/api/portfolio/performance/report-schedule")) return Promise.resolve(makeSchedule({ period_start: "2026-01-01", period_end: "2026-12-31", as_of_date: "2026-12-31", currency: schedCurr, xirr: "12.50", time_weighted_return: "8.30", money_weighted_return: "10.10", realized_pnl: "149.00", dividend_income: "42.50", dividend_yield: "2.36", holdings: [{ asset_identifier: "AAPL", quantity: "10.000000", cost_basis: "1500.00", market_value: "1800.00", unrealized_pnl: "300.00", realized_pnl: "149.00", dividend_income: "42.50", currency: "SGD" }], allocation: [{ dimension: "asset_class", category: "Public Equity", value: "1800.00", percentage: allocPct, count: 1 }, { dimension: "sector", category: "Technology", value: "1800.00", percentage: "100.00", count: 1 }], data_freshness: { latest_price_date: "2026-12-31", market_data_provider: "Test Broker", stale: false, stale_holdings: [], manual_override_basis: null }, source_links: ["brokerage_statement:aapl"], notes: ["Cost basis uses FIFO where available."] }));
    if (path.startsWith("/api/reports/net-worth/allocation")) {
      if (mode === "pending") return new Promise(() => undefined);
      if (mode === "error") return Promise.reject(new Error("allocation unavailable"));
      const excl = path.includes("include_restricted=false");
      return Promise.resolve({
        as_of_date: "2026-12-31", currency: "SGD", include_restricted: !excl, total_assets: "2100.00", total_liabilities: "100.00", net_worth: "2000.00",
        excluded_holdings: excl ? [{ asset_class: "restricted_comp", total_assets: "500.00", total_liabilities: "0.00", net_worth: "500.00" }] : [],
        rows: mode === "empty" ? [] : mode === "retirement_benefit"
          ? [{ asset_class: "retirement_and_benefit_assets", liquidity_class: "restricted", source_currency: "SGD", value: "185000.00", percentage_of_net_worth: "100.00", source_line_count: 1, source_lines: [{ source_type: "manual_valuation", source_id: "val1", label: "401k statement", value: "185000.00" }] }]
          : [
            { asset_class: "public_equity", liquidity_class: "liquid", source_currency: "USD", value: "1800.00", percentage_of_net_worth: allocPct, source_line_count: 2, source_lines: [{ source_type: "portfolio_market_adjustment", source_id: "acc1", label: "AAPL market value", value: "1800.00" }, { source_type: "manual_component", source_id: null, label: "Manual adjustment", value: "0.00" }] },
            { asset_class: "cash", liquidity_class: "liquid", source_currency: "SGD", value: "300.00", percentage_of_net_worth: "15.00", source_line_count: 1, source_lines: [{ source_type: "ledger_account", source_id: "acc1", label: "Main Bank", value: "300.00" }] },
            { asset_class: "liability", liquidity_class: "liability", source_currency: "SGD", value: "-100.00", percentage_of_net_worth: "-5.00", source_line_count: 1, source_lines: [{ source_type: "ledger_account", source_id: "loan1", label: "Loan", value: "-100.00" }] },
          ],
      });
    }
    if (path.startsWith("/api/reports/account-lineage")) return Promise.resolve({ account_id: "acc1", account_name: "Main Bank", account_type: "ASSET", currency: "SGD", as_of_date: "2026-12-31", start_date: null, total: "300.00", lines: [{ journal_line_id: u("8"), journal_entry_id: u("9"), entry_date: "2026-12-01", memo: "Salary deposit", direction: "DEBIT", original_amount: "300.00", original_currency: "SGD", amount: "300.00" }] });
    if (path.startsWith("/api/portfolio/holdings")) { const items = path.includes("include_disposed=true") ? [PORT_H1, PORT_H2] : holdings; return Promise.resolve({ items, total: items.length, warnings: [] }); }
    if (path === "/api/portfolio/AAPL/dividends" || path === "/api/portfolio/AAPL/realized") return Promise.resolve([]);
    if (path.startsWith("/api/pricing/manual-valuations")) return Promise.resolve({ items: [], total: 0 });
    return Promise.reject(new Error(`unhandled path ${path}`));
  }) as never);
}

// --- Balance sheet fixtures & router ---
export const mockBsApi = (api: AnyMock, payload: unknown) => api.mockImplementation(((op: string) => Promise.resolve(op === "balance_sheet_reports_balance_sheet_get" ? payload : { currency: "SGD", granularity: "monthly", points: [] })) as never);
export const BS_VAL = () => makeBalanceSheet({ as_of_date: "2026-10-23", assets: [{ account_id: "bank", name: "DBS Savings", type: "ASSET", parent_id: null, amount: "20385.65" }], liabilities: [{ account_id: "loan", name: "Valuation: Condo loan (mortgage balance)", type: "LIABILITY", parent_id: null, amount: "650000.00" }], equity: [{ account_id: "open", name: "Opening Balance", type: "EQUITY", parent_id: null, amount: "15000.00" }], total_assets: "1262385.65", total_liabilities: "650000.00", total_equity: "15000.00", net_income: "5360.65", unrealized_fx_gain_loss: "25.00", cta_adjustment: "0.00", net_worth_adjustment_gain_loss: "592000.00", excluded_holdings: [] });
export const BS_EXCL = () => makeBalanceSheet({ as_of_date: "2026-10-23", total_assets: "20360.65", total_liabilities: "0.00", total_equity: "15000.00", net_income: "5360.65", assets: [{ account_id: "bank", name: "DBS Savings", type: "ASSET", parent_id: null, amount: "20360.65" }], equity: [{ account_id: "open", name: "Opening Balance", type: "EQUITY", parent_id: null, amount: "15000.00" }], excluded_holdings: [{ asset_class: "real_estate", total_assets: "1200000.00", total_liabilities: "650000.00", net_worth: "550000.00", warnings: [] }, { asset_class: "restricted_comp", total_assets: "42000.00", total_liabilities: "0.00", net_worth: "42000.00", warnings: [] }, { asset_class: "retirement_and_benefit_assets", total_assets: null, total_liabilities: null, net_worth: null, warnings: [{ type: "missing_fx_rate_excluded_holding", source: "401k", currency: "USD", target_currency: "SGD", message: "No FX rate" }, { type: "fx_conversion_failed_excluded_holding", source: "MPF", currency: "HKD", target_currency: "SGD", message: "invalid FX" }] }] });
export const BS_TRANSIT = () => makeBalanceSheet({ as_of_date: "2026-02-01", total_assets: "1100.00", total_liabilities: "0.00", total_equity: "1100.00", assets: [{ account_id: "proc-1", name: "Processing", type: "ASSET", parent_id: null, amount: "-250.00", source_currency: "SGD", native_amount: "-250.00" }, { account_id: "cmb-1", name: "China Merchants Bank ••7788", type: "ASSET", parent_id: null, amount: "0.00", source_currency: "CNY", native_amount: "47939.43" }, { account_id: "usd-1", name: "IBKR USD Cash", type: "ASSET", parent_id: null, amount: "1350.00", source_currency: "USD", native_amount: "1000.00" }], fx_warnings: [{ type: "missing_fx_rate_partial_skip", base_currency: "CNY", quote_currency: "SGD", rate_date: "2026-02-01" }] });
export const BS_COLLAPSE = () => makeBalanceSheet({ as_of_date: "2026-02-01", total_assets: -500, total_liabilities: 0, total_equity: 0, equation_delta: 0, assets: [{ account_id: "a-root", name: "Cash", type: "ASSET", parent_id: null, amount: 1000 }, { account_id: "a-child", name: "Wallet", type: "ASSET", parent_id: "a-root", amount: 100 }], opening_balance_warnings: [{ type: "missing_opening_balance", message: "Record opening balances to trust this total." }] });
export const BS_CTA = () => ({ ...balanceSheetVector(), cta_adjustment: "142.50", total_assets: "24200.00", total_liabilities: "0.00", total_equity: "15450.75", net_income: "8749.25", equation_delta: "0.00", is_balanced: true, currency: "SGD" });
export const BS_LINEAGE_ASSETS = () => makeBalanceSheet({ as_of_date: "2026-02-01", total_assets: "43000.00", total_liabilities: "0.00", total_equity: "43000.00", assets: [{ account_id: "a-root", name: "Cash", type: "ASSET", parent_id: null, amount: "1000.00", provenance: "manual", allocation_source_type: "ledger_account" }, { account_id: "val-comp-1", name: "Valuation: CPF Ordinary Account (cpf balance)", type: "ASSET", parent_id: null, amount: "42000.00", provenance: "manual", allocation_source_type: "manual_valuation" }] });
export const BS_LINEAGE_RESP = { account_id: "a-root", account_name: "Cash", account_type: "ASSET", currency: "SGD", as_of_date: "2026-02-01", start_date: null, total: "1000.00", lines: [{ journal_line_id: u("8"), journal_entry_id: u("9"), entry_date: "2026-01-15", memo: "Opening deposit", direction: "DEBIT", original_amount: "1000.00", original_currency: "SGD", amount: "1000.00" }] };

// --- Workflow surfaces fixtures ---
export const mkWfSt = (o: Record<string, unknown> = {}): WorkflowStatusResponse => ({ primary_state: "ready", next_action: { type: "open_report", count: 1, href: "/reports/package", label: "Open report", summary: "R" }, report_readiness: { state: "ready", blocking_count: 0, href: "/reports/package" }, event_counts: { unread: 0, action_required: 0, blocked: 0 }, active_session: null, ...o }) as WorkflowStatusResponse;
export const mkWfEv = (id: string, sev: string, status: string, title: string, src: string, href: string, imp: string) => ({ id, user_id: "u1", session_id: "s1", occurred_at: "2026-06-03T08:00:00Z", family: `${src}.${sev}`, severity: sev, status, title, summary: "S", source_type: src, source_id: id, action_href: href, report_impact: imp, dedupe_key: id, created_at: "2026-06-03T08:00:00Z", updated_at: "2026-06-03T08:00:00Z" });
export const WF_SESS = { id: "s1", status: "active", title: "Upload-to-report session", summary: "S", started_at: "2026-06-03T05:00:00Z", last_event_at: "2026-06-03T08:00:00Z", source_count: 4, primary_state: "needs_action", report_readiness: { state: "blocked", blocking_count: 2, href: "/reports/package" }, event_counts: { unread: 3, action_required: 2, blocked: 1 } };
export const WF_ST_ACT = mkWfSt({ primary_state: "needs_action", next_action: { type: "review_required", count: 2, href: "/inbox", label: "Review required", summary: "C" }, report_readiness: { state: "blocked", blocking_count: 2, href: "/reports/package" }, event_counts: { unread: 3, action_required: 2, blocked: 1 }, active_session: WF_SESS });
export const WF_ST_EMPTY = mkWfSt({ primary_state: "empty", next_action: { type: "upload", count: 0, href: "/upload", label: "Upload statements", summary: "A" }, report_readiness: { state: "none", blocking_count: 0, href: "/reports/package" } });
export const WF_EVS: WorkflowEventListResponse = { total: 4, items: [mkWfEv("e1", "blocked", "unread", "Reconciliation blocked", "reconciliation", "/reconciliation?tab=unmatched", "blocked") as never, mkWfEv("e2", "action_required", "unread", "Review required", "bank_statement", "/inbox", "blocked") as never, mkWfEv("e3", "success", "read", "Safe entries posted", "journal", "/journal", "ready") as never, mkWfEv("e4", "info", "read", "Statement uploaded", "bank_statement", "/statements/s4", "processing") as never], sessions: [WF_SESS as never] };

// --- Cash flow fixtures & router ---
export const CF_LINE_OP = "list_cash_flow_line_events_reports_cash_flow_line_events_get";
export const cfLineEvt = (id: string, memo: string, amount: string, entry_date: string) => ({ journal_entry_id: id, journal_line_ids: [`${id}-cash`, `${id}-counter`], source_type: "system", source_id: null, decision_anchor_id: null, decision_authority_state: "anchored", event_types: [], activity: "Operating", reason_code: null, entry_date, memo, amount });
export const CF_FULL = () => makeCashFlow({ start_date: "2026-01-01", end_date: "2026-02-01", operating: [{ line_id: "operating-sales", category: "operating", subcategory: "Sales", amount: "1000", description: "Main ops", event_count: 1 }], investing: [{ line_id: "investing-etf", category: "investing", subcategory: "ETF", amount: "-300", description: null, event_count: 1 }], financing: [{ line_id: "financing-loan", category: "financing", subcategory: "Loan", amount: "200", description: null, event_count: 1 }], summary: { operating_activities: "1000", investing_activities: "-300", financing_activities: "200", net_cash_flow: "900", beginning_cash: "5000", ending_cash: "5900" }, fx_warnings: [{ type: "spot_rate_fallback", from_currency: "EUR", to_currency: "SGD", fallback_date: "2026-01-30" }] });
export function mockCfLineageApi(api: AnyMock, failOffset = false) {
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

// --- Dashboard / Home fixtures & router ---
export const HOME_FULL_BS = makeBalanceSheet({ as_of_date: "2026-10-22", currency: "USD", assets: [{ account_id: "a1", name: "Cash", type: "ASSET", amount: "3000" }, { account_id: "r1", name: "RSU", type: "ASSET", amount: "2000" }], liabilities: [{ account_id: "l1", name: "Card", type: "LIABILITY", amount: "1000" }], total_assets: "5000", total_liabilities: "1000", total_equity: "4000", excluded_holdings: [] });
export const HOME_LIQ_BS = { ...HOME_FULL_BS, assets: [HOME_FULL_BS.assets[0]], total_assets: "3000", total_equity: "2000", excluded_holdings: [{ asset_class: "restricted_comp", total_assets: "2000", total_liabilities: "0", net_worth: "2000" }] };
export const HOME_INC = makeIncomeStatement({ start_date: "2025-11-01", end_date: "2026-10-22", currency: "USD", income: [{ account_id: "i1", name: "Salary", type: "INCOME", amount: "3500" }], expenses: [{ account_id: "e1", name: "Rent", type: "EXPENSE", amount: "1200" }], total_income: "3500", total_expenses: "1200", net_income: "2300" });
export const HOME_CF = makeCashFlow({ start_date: "2025-11-01", end_date: "2026-10-22", currency: "USD", summary: { operating_activities: "2300", investing_activities: "0", financing_activities: "-300", net_cash_flow: "2000", beginning_cash: "3000", ending_cash: "5000" } });
export const HOME_READY_WF = { primary_state: "ready", next_action: { type: "open_report", count: 1, href: "/reports?tab=package", label: "Open report package", summary: "R" }, report_readiness: { state: "ready", blocking_count: 0, href: "/reports?tab=package" }, event_counts: { unread: 0, action_required: 0, blocked: 0 } };
export const homeWf = (s: string, na: Record<string, unknown>) => () => Promise.resolve({ ...HOME_READY_WF, primary_state: s, next_action: { count: 1, summary: "", ...na } });
export function mockHomeApi(api: AnyMock, ov: Record<string, () => Promise<unknown>> = {}) {
  api.mockImplementation(((op: string, r: { query?: Record<string, unknown> } = {}) => {
    if (ov[op]) return ov[op]();
    const map: Record<string, unknown> = {
      balance_sheet_reports_balance_sheet_get: r.query?.include_restricted === false ? HOME_LIQ_BS : HOME_FULL_BS,
      income_statement_reports_income_statement_get: HOME_INC, cash_flow_reports_cash_flow_get: HOME_CF,
      get_workflow_status_endpoint_workflow_status_get: HOME_READY_WF,
      list_statements_statements_get: { items: [{ id: "s1", status: "approved", original_filename: "dbs.pdf" }], total: 1 },
      reconciliation_stats_reconciliation_stats_get: { total_transactions: 20, matched_transactions: 20, unmatched_transactions: 0, pending_review: 0, auto_accepted: 4, match_rate: 100, score_distribution: {} },
      list_processing_pending_reconciliation_transfers_pending_get: { items: [], total: 0 },
      suggestions_chat_suggestions_get: { suggestions: [], structured_suggestions: [] },
      get_available_currencies_reports_currencies_get: ["SGD", "USD"],
      get_base_currency_users_me_settings_base_currency_get: { base_currency: "USD" },
    };
    return op in map ? Promise.resolve(map[op]) : Promise.reject(new Error(`unhandled ${op}`));
  }) as never);
}

// --- Reports cockpit fixtures & router ---
export const COCKPIT_READINESS = makeReadiness({ action_href: "/journal", blockers: [{ code: "pending_review", label: "Pending source review", severity: "blocking", count: 1, reason: "Review needed.", action_href: "/audit" }, { code: "missing_source_coverage", label: "Missing source coverage", severity: "blocking", count: 1, reason: "Anchors needed.", action_href: "/journal" }], input_coverage: { manifest_decision_count: 4, authoritative_input_count: 4, unproven_input_count: 2 } });
export const COCKPIT_READY = makeReadiness({ state: "ready", label: "Ready", action_href: "/journal", blocking_count: 0, blockers: [], input_coverage: { manifest_decision_count: 1, authoritative_input_count: 1, unproven_input_count: 0 } });
export const COCKPIT_BS = makeBalanceSheet({ as_of_date: "2026-10-22", assets: [{ account_id: "a1", name: "DBS Savings", type: "ASSET", amount: "12000.00" }], liabilities: [{ account_id: "l1", name: "Credit Card", type: "LIABILITY", amount: "2000.00" }], total_assets: "12000.00", total_liabilities: "2000.00", total_equity: "10000.00" });
export const COCKPIT_IS = makeIncomeStatement({ start_date: "2025-11-01", end_date: "2026-10-22", income: [{ account_id: "i1", name: "Salary", type: "INCOME", amount: "60000.00" }], expenses: [{ account_id: "e1", name: "Rent", type: "EXPENSE", amount: "24000.00" }], total_income: "60000.00", total_expenses: "24000.00", net_income: "36000.00" });
export const COCKPIT_CF = makeCashFlow({ start_date: "2025-11-01", end_date: "2026-10-22", summary: { operating_activities: "36000.00", investing_activities: "-5000.00", financing_activities: "0.00", net_cash_flow: "31000.00", beginning_cash: "0.00", ending_cash: "31000.00" } });
export const mockCockpitApi = (api: AnyMock, pkg: () => Promise<unknown> = () => Promise.resolve(normalizablePackageDocument({ readiness: COCKPIT_READINESS }))) =>
  api.mockImplementation(((op: string) => {
    if (op === "preview_personal_report_package_reports_package_get") return pkg();
    if (op === "balance_sheet_reports_balance_sheet_get") return Promise.resolve(COCKPIT_BS);
    if (op === "income_statement_reports_income_statement_get") return Promise.resolve(COCKPIT_IS);
    if (op === "cash_flow_reports_cash_flow_get") return Promise.resolve(COCKPIT_CF);
    return Promise.resolve({});
  }) as never);

// --- Report filters fixtures & router ---
export const RF_TODAY = new Date(2026, 9, 22);
export const RF_PRESETS = { "1M": "2026-10-01", "1Q": "2026-08-01", "1Y": "2025-11-01", YTD: "2026-01-01", "3Y": "2023-11-01", All: "2000-01-01" } as const;
export const RF_STEP_CASES = [
  ["period=1M", { startDate: "2026-10-01", endDate: "2026-10-22", isCurrent: true, openingDate: "2026-09-30", nextEnd: null }],
  ["period=1M&end=2026-09-30", { startDate: "2026-09-01", endDate: "2026-09-30", isCurrent: false, openingDate: "2026-08-31", nextEnd: "" }],
  ["period=1M&end=2026-08-31", { startDate: "2026-08-01", nextEnd: "2026-09-30" }],
  ["period=1Q&end=2026-07-31", { startDate: "2026-05-01", endDate: "2026-07-31", nextEnd: "" }],
  ["period=1Q&end=2026-04-30", { startDate: "2026-02-01", nextEnd: "2026-07-31" }],
  ["end=2025-10-31", { preset: "1Y", startDate: "2024-11-01", nextEnd: "" }],
  ["period=YTD&end=2024-12-31", { startDate: "2024-01-01", openingDate: "2023-12-31", nextEnd: "2025-12-31" }],
  ["period=3Y&end=2023-10-31", { startDate: "2020-11-01", nextEnd: "" }],
  ["period=All&end=2025-01-31", { startDate: "2000-01-01", openingDate: null, nextEnd: null }],
] as const;
export const RF_URL_CASES = [
  ["tab=cash-flow&period=YTD&end=2026-03-31&currency=USD&include_restricted=false", { tab: "cash-flow", preset: "YTD", startDate: "2026-01-01", endDate: "2026-03-31", currency: "USD", includeRestricted: false, dimensionQuery: "period=YTD&end=2026-03-31&currency=USD&include_restricted=false" }],
  ["include_restricted=true", { includeRestricted: true, dimensionQuery: "" }],
  ["tab=ledger&period=2W&end=2026-13-01&currency=usd&include_restricted=yes", { tab: "overview", preset: "1Y", endDate: "2026-10-22", isCurrent: true, currency: undefined, includeRestricted: true, dimensionQuery: "" }],
  ["end=2026-02-30", { isCurrent: true }],
  ["period=1Y&end=2026-12-31", { startDate: "2026-01-01", endDate: "2026-12-31", isCurrent: false, nextEnd: null }],
  ["period=1M&start=2025-02-15&end=2025-03-14", { preset: null, startDate: "2025-02-15", endDate: "2025-03-14", openingDate: "2025-02-14", previousEnd: null, nextEnd: null, dimensionQuery: "start=2025-02-15&end=2025-03-14" }],
  ["start=2026-09-01", { preset: null, startDate: "2026-09-01", endDate: "2026-10-22", isCurrent: true }],
  ["start=2025-04-01&end=2025-03-31", { preset: "1Y", startDate: "2024-04-01", endDate: "2025-03-31" }],
  ["as_of_date=2025-12-31", { endDate: "2025-12-31" }],
  ["start_date=2025-01-01&end_date=2025-06-30", { preset: null, startDate: "2025-01-01", endDate: "2025-06-30" }],
] as const;
export const RF_COV = { start: "2026-07-01", limitingAccounts: ["OCBC Bank"] };
export const RF_COV_CASES = [
  ["", { preset: "1Y", startDate: "2026-07-01", openingDate: "2026-07-01", isDefaultPeriod: true, opensAtCoverageStart: true, coverageLimitingAccounts: ["OCBC Bank"], previousEnd: null, nextEnd: null, dimensionQuery: "" }],
  ["end=2026-09-30", { startDate: "2026-07-01", openingDate: "2026-07-01", previousEnd: null, nextEnd: "", dimensionQuery: "end=2026-09-30" }],
  ["period=2W", { isDefaultPeriod: true, startDate: "2026-07-01", opensAtCoverageStart: true }],
  ["end=2026-05-31", { startDate: "2025-06-01", openingDate: "2025-05-31", opensAtCoverageStart: false, coverageLimitingAccounts: [], previousEnd: "2025-05-31" }],
  ["period=1Y", { preset: "1Y", startDate: "2025-11-01", isDefaultPeriod: false, opensAtCoverageStart: false, previousEnd: "2025-10-31" }],
  ["period=All", { startDate: "2026-07-01", openingDate: "2026-07-01", opensAtCoverageStart: true, previousEnd: null }],
  ["period=3Y", { startDate: "2023-11-01", previousEnd: "2023-10-31" }],
  ["period=1Q&end=2026-09-30", { startDate: "2026-07-01", openingDate: "2026-06-30", previousEnd: "2026-06-30", nextEnd: "" }],
  ["start=2026-01-01&end=2026-09-30", { preset: null, startDate: "2026-01-01", opensAtCoverageStart: false }],
] as const;
export const mockFilterBarApi = (api: AnyMock, coverage: () => Promise<unknown> = () => Promise.resolve({ as_of_date: "2026-01-31", coverage_start: null })) =>
  api.mockImplementation(((op: string, req?: { query?: { as_of_date?: string } }) => {
    if (op === "get_available_currencies_reports_currencies_get") return Promise.resolve(["SGD", "USD", "EUR"]);
    if (op === "get_base_currency_users_me_settings_base_currency_get") return Promise.resolve({ base_currency: "EUR" });
    if (op === "report_coverage_reports_coverage_get") return coverage();
    return Promise.reject(new Error(`unexpected ${op} ${req?.query?.as_of_date ?? ""}`));
  }) as never);

// --- Audit & Data Quality Observatory fixtures ---
const dqInv = (name: string, delta = "0") => ({ is_healthy: true, name, summary: "OK", detail: "", delta });
export const AUDIT_HEALTH_A = { score: 99, grade: "A_AUDIT_READY", as_of_date: "2026-10-22", currency: "SGD", equation_invariant: dqInv("Equation"), temporal_continuity_invariant: dqInv("Cont"), reconciliation_purity_invariant: dqInv("Pure"), lineage_anchors_invariant: dqInv("Lin"), timeline: [], action_items: [] };
export const auditStats = (unmatched: number, pending_review = 0) => ({ total_transactions: 10, matched_transactions: 10 - unmatched, unmatched_transactions: unmatched, pending_review, auto_accepted: 5, match_rate: 70, score_distribution: {} });
export const auditWf = (s: string) => ({ primary_state: s, next_action: { type: "resolve_blocker", count: 1, href: "/reports?tab=package", label: "Resolve blocker", summary: "" }, report_readiness: { state: s === "blocked" ? "blocked" : "ready", blocking_count: s === "blocked" ? 1 : 0, href: "/reports" }, event_counts: { unread: 0, action_required: 0, blocked: 0 } });
export const mockAuditApi = (api: AnyMock, o: Record<string, unknown> = {}) => api.mockImplementation((async (op: string) => (op in o ? o[op] : op === "get_data_quality_health_reports_data_quality_get" ? Promise.reject(new Error("off")) : op === "reconciliation_stats_reconciliation_stats_get" ? auditStats(0) : { items: [] })) as never);
export const DQ_HEALTH: PersonalDataQualityHealthResponse = {
  score: 96, grade: "A_AUDIT_READY", as_of_date: "2026-10-09", currency: "SGD",
  equation_invariant: dqInv("Accounting Equation Balance", "0.00"), temporal_continuity_invariant: dqInv("Temporal Continuity & Rollforward"),
  reconciliation_purity_invariant: dqInv("Reconciliation & Debt Clearance Purity"), lineage_anchors_invariant: dqInv("Evidence Lineage & Traceability Anchors"),
  timeline: [
    { month: "2026-01", statement_count: 1, has_gap: false, opening_balance: "1000.00", closing_balance: "1500.00", net_movement: "500.00", status: "HEALTHY" },
    { month: "2026-02", statement_count: 0, has_gap: true, opening_balance: null, closing_balance: null, net_movement: null, status: "GAP_DETECTED" },
    { month: "2026-03", statement_count: 1, has_gap: false, opening_balance: "1500.00", closing_balance: "1600.00", net_movement: "100.00", status: "PENDING_PROCESSING" },
    { month: "2026-04", statement_count: 0, has_gap: false, opening_balance: null, closing_balance: null, net_movement: null, status: "HEALTHY" },
  ],
  action_items: [{ id: "u1", priority: "P1", title: "Upload Statement for 2026-02", description: "M", score_boost: 10, action_type: "UPLOAD_STATEMENT", action_url: "/upload?month=2026-02" }],
};

// --- Income statement, Sankey, Holding detail, Prices, Drilldown, HoldingsTable, Schedule ---
export const IS_EMPTY = () => makeIncomeStatement({ start_date: "2026-01-01", end_date: "2026-02-01", total_income: 0, total_expenses: 0, net_income: 0 });
export const IS_FILLED = () => makeIncomeStatement({ start_date: "2026-01-01", end_date: "2026-02-01", income: [{ account_id: "i1", name: "Salary", type: "INCOME", amount: "5000", provenance: "imported" }], expenses: [{ account_id: "e1", name: "Rent", type: "EXPENSE", amount: "1200", provenance: "manual" }], total_income: "5000", total_expenses: "1200", net_income: "3800", fx_warnings: [{ type: "missing_average_rate", from_currency: "USD", to_currency: "SGD", date: "2026-01-31" }], trends: [{ period_start: "2026-01-01", period_end: "2026-01-31", total_income: "5000", total_expenses: "1200", net_income: "3800" }] });
export const IS_LINEAGE = { account_id: "i1", account_name: "Salary", account_type: "INCOME", currency: "SGD", as_of_date: "2026-02-01", start_date: "2026-01-01", total: "5000.00", lines: [{ journal_line_id: u("a"), journal_entry_id: u("b"), entry_date: "2026-01-25", memo: "January payroll", direction: "CREDIT", original_amount: "5000.00", original_currency: "SGD", amount: "5000.00" }] };

export const SANKEY_DEFAULT_COLORS = { "--success": "#1f9d55", "--error": "#e11d48", "--accent": "#2563eb", "--warning": "#f59e0b", "--foreground": "#0f172a", "--foreground-muted": "#64748b" };
export function stubSankeyGlobals(colors: Record<string, string>, setCb: (cb: (m: MutationRecord[]) => void) => void) {
  vi.stubGlobal("getComputedStyle", vi.fn(() => ({ getPropertyValue: (n: string) => colors[n] ?? "#888" })));
  vi.stubGlobal("MutationObserver", class { constructor(cb: (m: MutationRecord[]) => void) { setCb(cb); } observe() {} disconnect() {} });
}
export const SANKEY_DETAIL_DATA = {
  title: "Detailed Cash Flow",
  operating: [{ category: "operating" as const, subcategory: "Sales", amount: "300" }, { category: "operating" as const, subcategory: "Payroll", amount: "-120" }, { category: "operating" as const, subcategory: "Invalid", amount: "NaN" }],
  investing: [{ category: "investing" as const, subcategory: "Equipment", amount: "-80" }],
  financing: [{ category: "financing" as const, subcategory: "Loan", amount: "220" }],
};
export const SANKEY_DUP_DATA = { title: "Dup", operating: [{ category: "operating" as const, subcategory: "Transfer", amount: "100" }, { category: "operating" as const, subcategory: "Transfer", amount: "200" }, { category: "operating" as const, subcategory: "Transfer", amount: "-50" }] };
export const SANKEY_SEP_DATA = { title: "Sep", operating: [{ category: "operating" as const, subcategory: "Alpha -> Beta", amount: "150" }, { category: "operating" as const, subcategory: "Alpha -> Beta", amount: "50" }] };
export type SankeyOpt = { title: { text: string }; graphic: unknown; tooltip: { formatter: (p: { data: { name?: string; value?: number; source?: string; target?: string } }) => string }; series: Array<{ data: Array<{ name: string; label?: { position?: string }; itemStyle?: { color: string } }>; links: Array<{ source: string; target: string; value: number }>; label: { formatter: (p: { name: string }) => string } }> };
export function assertSankeyEmpty(props: { option?: unknown; style?: unknown } | null, loading: ReactNode) {
  expect(props?.style).toEqual({ height: "320px", width: "100%" });
  expect(props?.option).toMatchObject({ title: { text: "Cash Flow", left: "center", textStyle: { color: "#64748b" } }, graphic: { type: "text", left: "center", top: "middle", style: { text: "Add transaction data to see cash flow visualization", fill: "#64748b", fontSize: 14 } } });
  fireEvent.click(document.body);
  void loading;
}
export function assertSankeyDetail(props: { option?: Record<string, unknown>; notMerge?: boolean } | null) {
  const opt = props?.option as SankeyOpt, s = opt.series[0], names = s.data.map((n) => n.name);
  expect(props?.notMerge).toBe(true); expect(opt.title.text).toBe("Detailed Cash Flow"); expect(opt.graphic).toEqual([]);
  for (const a of ["Operating", "Investing", "Financing"]) expect(names).not.toContain(a);
  for (const p of ["Operating-Inflows", "Operating-Outflows", "Operating-Sales", "Operating-Payroll", "Investing-Equipment", "Financing-Loan"]) expect(names).toContain(p);
  expect(s.data.find((n) => n.name === "Operating-Sales")?.label?.position).toBe("left");
  expect(s.data.find((n) => n.name === "Operating-Outflows")?.label?.position).toBe("left");
  for (const [k, v] of [["Operating-Inflows", "Operating Inflows"], ["Operating-Outflows", "Operating Outflows"], ["Operating-Sales", "Sales"], ["Investing-Equipment", "Equipment"]]) expect(s.label.formatter({ name: k })).toBe(v);
  expect(s.links).toEqual(expect.arrayContaining([{ source: "Operating-Inflows", target: "Operating-Sales", value: 300 }, { source: "Operating-Payroll", target: "Operating-Outflows", value: 120 }, { source: "Investing-Equipment", target: "Investing-Outflows", value: 80 }, { source: "Financing-Inflows", target: "Financing-Loan", value: 220 }]));
  expect(opt.tooltip.formatter({ data: { source: "Operating-Inflows", target: "Operating-Sales", value: 3000 } })).toBe("Operating Inflows → Sales: 3,000");
  expect(opt.tooltip.formatter({ data: { name: "Operating-Sales", value: 12 } })).toBe("Sales: 12");
}
export async function assertSankeyDedup(opt: SankeyOpt) {
  const echarts = await import("echarts");
  const names = opt.series[0].data.map((n) => n.name);
  expect(names.length).toBe(new Set(names).size);
  expect(opt.series[0].links.find((l) => l.source === "Operating-Inflows" && l.target === "Operating-Transfer")?.value).toBe(300);
  const el = document.createElement("div"); Object.defineProperty(el, "clientWidth", { value: 500 }); Object.defineProperty(el, "clientHeight", { value: 500 });
  const chart = echarts.init(el, null, { renderer: "svg", ssr: true, width: 500, height: 500 });
  expect(() => chart.setOption(opt as never)).not.toThrow(); chart.dispose();
}

export const HD_ACTIVE = makeHolding({ cost_basis_method: "FIFO" });
export const HD_DISPOSED = makeHolding({ id: "h2", quantity: "5", cost_basis: "700.00", market_value: "0.00", unrealized_pnl: "0.00", unrealized_pnl_percent: "0.00", acquisition_date: "2024-06-01", disposal_date: "2025-02-01", status: "disposed", cost_basis_method: "FIFO" });
export const HD_DIV = { id: "d1", ex_date: "2026-02-10", pay_date: "2026-02-15", amount: "42.50", currency: "USD", reinvested: false };
export const HD_LOT = { lot_id: "11111111-2222-3333-4444-555555555555", acquired_date: "2025-01-15", sold_date: "2026-03-01", quantity: "5.000000", basis: "500.00", proceeds: "650.00", gain_loss: "150.00", holding_period: 410, currency: "USD" };
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

export const PRICE_HOLDINGS_RES = { items: [makeHolding(), makeHolding({ id: "h2", asset_identifier: "TSLA", quantity: "5", cost_basis: "1000.00", market_value: "900.00" })], total: 2, warnings: [] };
export const PRICE_OK_RES = { updated_count: 1, results: [{ success: true, message: "Updated", asset_identifier: "AAPL", price_date: "2026-04-06", price: "180.00", currency: "USD", source: "manual" }] };
export const priceForm = () => screen.getByText("Update Prices").closest("form") as HTMLFormElement;
export const fillPriceInputs = (tickerVal: string | null, priceVal: string) => {
  if (tickerVal !== null) fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value: tickerVal } });
  fireEvent.change(screen.getByPlaceholderText("0.00"), { target: { value: priceVal } });
};
export const checkPriceRows = () => {
  fireEvent.click(screen.getByRole("button", { name: "Add Row" }));
  expect(screen.getAllByRole("combobox")).toHaveLength(2);
  fireEvent.click(screen.getAllByLabelText("Remove row")[1]);
  expect(screen.getAllByRole("combobox")).toHaveLength(1);
};
export const checkPriceCurrencyDate = () => {
  const ticker = screen.getByPlaceholderText("AAPL, MSFT...");
  expect(ticker.tagName).toBe("INPUT");
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  const cur = screen.getAllByDisplayValue("USD")[0], dt = screen.getByDisplayValue(/^\d{4}-\d{2}-\d{2}$/);
  fireEvent.change(cur, { target: { value: "eur" } }); expect(cur).toHaveValue("EUR");
  fireEvent.change(dt, { target: { value: "2026-01-15" } }); expect(dt).toHaveValue("2026-01-15");
  fireEvent.change(ticker, { target: { value: "GOOG" } });
  fillPriceInputs(null, "100.00");
};

export const BSD_TARGET = { accountId: u("2"), accountName: "Checking", asOfDate: "2026-01-31", currency: "SGD" };
export const BSD_BASE = { account_id: BSD_TARGET.accountId, account_name: "Checking", account_type: "ASSET", currency: "SGD", as_of_date: "2026-01-31", start_date: null };
export const BSD_LINES = { ...BSD_BASE, total: "750.00", lines: [{ journal_line_id: u("3"), journal_entry_id: u("4"), entry_date: "2026-01-10", memo: "Salary", direction: "DEBIT", original_amount: "1000.00", original_currency: "SGD", amount: "1000.00" }, { journal_line_id: u("5"), journal_entry_id: u("4"), entry_date: "2026-01-12", memo: "", direction: "CREDIT", original_amount: "250.00", original_currency: "SGD", amount: "-250.00" }] };
export const BSD_EV = { anchor: null, max_depth: 6, blockers: [], edges: [], nodes: [{ id: "n1", node_kind: "ledger_line", entity_type: "journal_line", entity_id: "j1", properties: {} }, { id: "n4", node_kind: "source_document", entity_type: "uploaded_document", entity_id: "d1", properties: {} }] };
export async function assertBsdEmptyErrNull(api: AnyMock & { mockReset: () => void; mockImplementationOnce: (fn: never) => unknown }, Drawer: React.ComponentType<{ target: typeof BSD_TARGET | null; onClose: () => void }>) {
  for (const [fn, msg] of [[() => Promise.resolve({ ...BSD_BASE, total: "0.00", lines: [] }), "No source transactions contribute to this balance yet."], [() => Promise.reject(new Error("boom")), "boom"]] as const) {
    api.mockImplementationOnce(fn as never); const v = render(React.createElement(Drawer, { target: BSD_TARGET, onClose: () => {} })); await see(msg); v.unmount();
  }
  api.mockReset(); render(React.createElement(Drawer, { target: null, onClose: () => {} }));
  expect(screen.queryByRole("dialog")).toBeNull(); expect(api).not.toHaveBeenCalled();
}

export const HT_BASE = makeHolding({ id: "h1", asset_identifier: "FOO", quantity: "10.5", cost_basis: "1000.00", market_value: "1200.00", unrealized_pnl: "200.00", unrealized_pnl_percent: "20.00", account_name: "BrokerA", sector: undefined });
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
export const COCKPIT_TABS = ["Overview", "Balance sheet", "Income statement", "Cash flow", "Full package"];
export const COCKPIT_STATES = [["ready", "Ready", "badge-success"], ["generated", "Generated", "badge-success"], ["processing", "Processing", "badge-warning"], ["stale", "Stale", "badge-error"], ["draft", "Draft", "badge-muted"]] as const;
export const RF_NONE_COVS = [null, { start: null, limitingAccounts: [] }, { start: "2026-02-30", limitingAccounts: ["OCBC Bank"] }] as const;
export const DQ_GRADES = [["A_AUDIT_READY", "Grade A · Audit-Ready", "var(--success)"], ["B_BALANCED_GAPS", "Grade B · Balanced with Gaps", "var(--accent)"], ["C_ATTENTION_NEEDED", "Grade C · Attention Needed", "var(--warning)"], ["D_OUT_OF_BALANCE", "Grade D · Out of Balance", "var(--error)"]] as const;
export const DQ_INV_TEXTS = ["Accounting Equation Balance", "Temporal Continuity & continuity", "Reconciliation & Debt Clearance Purity", "Evidence Lineage & Traceability Anchors", "Assets = Liabilities + Equity (Δ = 0.00)", "Statement Anchors + 3198 Gap Calibration"];
export const DQ_TIMELINE_TEXTS = ["Missing Period", "Upload", "Review", "Zero-change verified"];
export const DQ_ACTION_FX = [{ id: "fx", priority: "P1" as const, title: "A Restricted Holding Has No FX Rate", description: "D", score_boost: 0, action_type: "RESOLVE_FX_RATE" as const, action_url: "/portfolio?panel=evidence" }];
export const AUDIT_BOOKS_LINKS = [[/Reconciliation/, "/reconciliation"], [/Journal/, "/journal"], [/Statements/, "/upload"]] as const;
export const AUDIT_NEEDS_YOU = {
  list_statements_statements_get: { items: [{ id: "s1", original_filename: "may.pdf", status: "parsed", confidence_score: 55, balance_validated: true }] },
  reconciliation_stats_reconciliation_stats_get: { total_transactions: 10, matched_transactions: 7, unmatched_transactions: 3, pending_review: 2, auto_accepted: 5, match_rate: 70, score_distribution: {} },
  list_classification_suggestions_statements_classification_suggestions_get: { items: [{ suggestion_id: "a1", transaction: "COFFEE SHOP", suggested_category_or_match: "Dining", ai_score: 72, ai_reasoning: "M", direction: "OUT" }] },
};
export const AUDIT_AUTO_DATA = {
  list_statements_statements_get: { items: [{ id: "s1", original_filename: "oct.csv", status: "parsed", confidence_score: 80 }] },
  reconciliation_stats_reconciliation_stats_get: { total_transactions: 10, matched_transactions: 9, unmatched_transactions: 1, pending_review: 0, auto_accepted: 5, match_rate: 70, score_distribution: {} },
  list_unmatched_reconciliation_unmatched_get: { items: [{ id: "t1", description: "PayNow REF 4471" }], total: 1 },
  list_classification_suggestions_statements_classification_suggestions_get: { items: [{ suggestion_id: "a1", transaction: "COFFEE SHOP", suggested_category_or_match: "Dining", ai_score: 72, ai_reasoning: "M", direction: "OUT" }], total: 1 },
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
export async function runDqObsScenarios(api: AnyMock, Page: React.ComponentType) {
  setTestUrl("/audit");
  api.mockImplementation((async (op: string) => op === "list_statements_statements_get" ? { items: [{ id: "s1", institution: "DBS", original_filename: "DBS_2026_01.pdf", status: "parsed", confidence_score: 65, balance_validated: false, period_start: "2026-01-01", period_end: "2026-01-31", transactions: [] }] } : op === "reconciliation_stats_reconciliation_stats_get" ? auditStats(2, 1) : op.includes("pending") || op.includes("classification") ? { items: [] } : DQ_HEALTH) as never);
  const v1 = render(React.createElement(Page)); await see("DBS_2026_01.pdf");
  act(() => setTestUrl("/audit?tab=health")); await see("Open items remain"); clk(/Re-evaluate/i);
  act(() => setTestUrl("/audit?tab=books")); expect(lnk(/Statements/)).toHaveAttribute("href", "/upload"); v1.unmount();

  setTestUrl("/audit");
  api.mockImplementation((async (op: string) => op === "list_statements_statements_get" || op.includes("pending") ? Promise.reject(new Error("fail")) : op === "reconciliation_stats_reconciliation_stats_get" ? auditStats(3) : op.includes("classification") ? { items: [] } : DQ_HEALTH) as never);
  const v2 = render(React.createElement(Page));
  expect(within(await within(await fTid("needs-confirmation-queue")).findByRole("link", { name: /3 unmatched transactions/ })).getByText("0% confidence")).toBeInTheDocument(); v2.unmount();

  api.mockImplementation((async (op: string) => (op === "reconciliation_stats_reconciliation_stats_get" ? Promise.reject(new Error("s")) : op === "list_statements_statements_get" ? { items: [{ id: "s2", original_filename: "OCBC.pdf", status: "parsed", confidence_score: 65, balance_validated: false }] } : op.includes("pending") || op.includes("classification") ? { items: [] } : DQ_HEALTH)) as never);
  const v3 = render(React.createElement(Page));
  expect(within(await within(await fTid("needs-confirmation-queue")).findByRole("link", { name: /OCBC\.pdf/ })).getByText("40% confidence")).toBeInTheDocument(); v3.unmount();

  let n = 0; api.mockImplementation((async (op: string) => (op === "get_data_quality_health_reports_data_quality_get" ? (++n === 1 ? Promise.reject(new Error("Net")) : DQ_HEALTH) : { items: [] })) as never);
  render(React.createElement(Page)); await see("Failed to evaluate data quality health."); clk("Retry Evaluation");
}
export async function assertFilterPresetsAndCustom(api: { mock: { calls: unknown[][] } }, Bar: React.ComponentType<{ showScope?: boolean }>) {
  render(React.createElement(Bar));
  expect(screen.getByRole("group", { name: "Reporting period" })).toBeInTheDocument();
  for (const p of ["1M", "1Q", "1Y", "YTD", "3Y", "All"]) expect(btn(`Period ${p}`)).toHaveAttribute("aria-pressed", String(p === "1M"));
  expect(tid("report-period-range")).toHaveTextContent("Jan 1, 2026 – Jan 31, 2026");
  await waitFor(() => expect(api.mock.calls.map(([id]) => id)).toContain("get_available_currencies_reports_currencies_get"));
  expect(api.mock.calls.map(([id]) => id)).not.toContain("report_coverage_reports_coverage_get");
  clk("Previous period"); expect(testUrl()).toBe("/reports?tab=cash-flow&period=1M&end=2025-12-31");
  expect(tid("report-period-range")).toHaveTextContent("Dec 1, 2025 – Dec 31, 2025");
  clk("Next period"); expect(testUrl()).toBe("/reports?tab=cash-flow&period=1M&end=2026-01-31");
  clk("Period YTD"); expect(testUrl()).toBe("/reports?tab=cash-flow&period=YTD"); dis("Next period");
  clk("Period All"); dis("Previous period"); expect(screen.queryByLabelText("Include restricted holdings")).toBeNull();
  act(() => setTestUrl("/reports?tab=cash-flow&period=1M&end=2026-01-31"));
  clk("Custom period"); expect(testUrl()).toBe("/reports?tab=cash-flow&start=2026-01-01&end=2026-01-31");
  expect(screen.queryByRole("button", { name: "Previous period" })).toBeNull();
  for (const [l, v, u] of [["Period start", "2025-12-15", "/reports?tab=cash-flow&start=2025-12-15&end=2026-01-31"], ["Period end", "2025-12-01", "/reports?tab=cash-flow&start=2025-12-01&end=2025-12-01"]] as const) { fireEvent.change(lbl(l), { target: { value: v } }); expect(testUrl()).toBe(u); }
  fireEvent.change(lbl("Period start"), { target: { value: "2025-12-20" } }); fireEvent.change(lbl("Period end"), { target: { value: "" } });
  expect(testUrl()).toBe("/reports?tab=cash-flow&start=2025-12-20&end=2025-12-20");
  clk("Period 1Q"); expect(testUrl()).toBe("/reports?tab=cash-flow&period=1Q"); expect(screen.queryByLabelText("Period start")).toBeNull();
}
export async function assertFilterCoverage(api: AnyMock, Bar: React.ComponentType<{ showScope?: boolean }>, coverageNote: (d: string, a: string[]) => string) {
  for (const [a, e] of [[["OCBC Bank"], "Starts Oct 1, 2026: OCBC Bank has no opening balance before this date."], [["A", "B", "C"], "Starts Oct 1, 2026: A, B and C have no opening balance before this date."], [[], "Starts Oct 1, 2026: Your cash accounts have no opening balance before this date."]] as const) expect(coverageNote("2026-10-01", [...a])).toBe(e);
  const { promise, resolve } = deferred(); mockFilterBarApi(api, () => promise); setTestUrl("/reports?end=2026-01-31");
  render(React.createElement(Bar));
  expect(tid("report-period-range")).toHaveTextContent("…"); dis("Previous period"); dis("Custom period");
  clk("Previous period"); expect(testUrl()).toBe("/reports?end=2026-01-31");
  await act(async () => { resolve({ as_of_date: "2026-01-31", coverage_start: "2026-01-15", limiting_accounts: ["DBS Savings", "OCBC Bank"] }); await promise; });
  await waitFor(() => expect(tid("report-period-range")).toHaveTextContent("Jan 15, 2026 – Jan 31, 2026"));
  expect(tid("report-coverage-note")).toHaveTextContent("Starts Jan 15, 2026: DBS Savings and OCBC Bank have no opening balance before this date. Add an opening balance");
  expect(lnk("Add an opening balance")).toHaveAttribute("href", "/settings?tab=accounts");
  dis("Previous period"); en("Custom period");
  clk("Period 1Y"); expect(testUrl()).toBe("/reports?period=1Y");
  act(() => setTestUrl("/reports?period=1Y&end=2026-01-31"));
  expect(tid("report-period-range")).toHaveTextContent("Feb 1, 2025 – Jan 31, 2026"); expect(screen.queryByTestId("report-coverage-note")).toBeNull();
  clk("Previous period"); expect(testUrl()).toBe("/reports?period=1Y&end=2025-01-31");
}
export function assertHookUrlUpdates(useReportFilters: () => { setIncludeRestricted: (v: boolean) => void; setCurrency: (v: string) => void; tab: string; endDate: string; setPreset: (p: "1M" | "1Q" | "1Y") => void; goToPeriodEnd: (d: string) => void; openingDate: string | null; isCurrent: boolean }) {
  setTestUrl("/reports?tab=balance-sheet&as_of_date=2025-12-31&currency=SGD");
  const { result, unmount } = renderHook(() => useReportFilters());
  act(() => result.current.setIncludeRestricted(false)); expect(testUrl()).toBe("/reports?tab=balance-sheet&end=2025-12-31&currency=SGD&include_restricted=false");
  act(() => setTestUrl("/reports?tab=income-statement&start_date=2025-01-01&end_date=2025-06-30"));
  act(() => result.current.setCurrency("USD")); expect(testUrl()).toBe("/reports?tab=income-statement&start=2025-01-01&end=2025-06-30&currency=USD");
  unmount();
  setTestUrl("/reports?from=audit&tab=income-statement&end_date=2025-06-30");
  const h = renderHook(() => useReportFilters());
  expect(h.result.current).toMatchObject({ tab: "income-statement", endDate: "2025-06-30" });
  act(() => h.result.current.setPreset("1M")); expect(testUrl()).toBe("/reports?tab=income-statement&period=1M&from=audit");
  act(() => h.result.current.goToPeriodEnd(h.result.current.openingDate!));
  expect(h.result.current.isCurrent).toBe(false); expect(testUrl()).toMatch(/&end=\d{4}-\d{2}-\d{2}&from=audit$/);
  act(() => h.result.current.setPreset("1Q")); act(() => h.result.current.setPreset("1M")); act(() => h.result.current.goToPeriodEnd(""));
  act(() => h.result.current.setCurrency("USD")); act(() => h.result.current.setIncludeRestricted(false));
  expect(testUrl()).toBe("/reports?tab=income-statement&period=1M&currency=USD&include_restricted=false&from=audit");
  act(() => h.result.current.setIncludeRestricted(true)); act(() => h.result.current.setPreset("1Y"));
  expect(routerReplace).toHaveBeenLastCalledWith("/reports?tab=income-statement&period=1Y&currency=USD&from=audit", { scroll: false });
}
export async function assertAuditBooksAndQueue(api: AnyMock, Page: React.ComponentType) {
  setTestUrl("/audit?tab=books");
  const v1 = render(React.createElement(Page)); const panel = screen.getByRole("tabpanel");
  for (const [n, h] of AUDIT_BOOKS_LINKS) expect(lnk(n, panel).closest("a")).toHaveAttribute("href", h); v1.unmount();
  setTestUrl("/audit?tab=needs-you"); mockAuditApi(api, AUDIT_NEEDS_YOU);
  render(React.createElement(Page)); const qEl = tid("needs-confirmation-queue");
  expect(await fHdg("Suggestions to review")).toBeInTheDocument();
  for (const l of screen.queryAllByRole("link")) expect(l.getAttribute("href")).not.toMatch(/^\/(attention|confidence|review\/ai-suggestions)/);
  for (const j of [/TraceRecord/i, /Stage2/i, /Layer-2/i]) noTxt(j);
  expect((await within(qEl).findAllByRole("link")).map((l) => l.getAttribute("href"))).toEqual(["/reconciliation?tab=unmatched&from=attention", "/statements/s1?from=attention", "/reconciliation?tab=matches&from=attention"]);
  expect((await fAllTxt("COFFEE SHOP")).length).toBeGreaterThan(0); expect(screen.getAllByRole("button", { name: "Accept" }).length).toBeGreaterThan(0);
}
export async function assertAuditAutoSelect(api: AnyMock, Page: React.ComponentType, tabs: () => HTMLElement[], selTab: () => HTMLElement | undefined) {
  mockAuditApi(api, AUDIT_AUTO_DATA); const v1 = render(React.createElement(Page));
  expect(selTab()).toBeUndefined(); expect(await fTid("needs-you-count")).toHaveTextContent("2"); expect(selTab()).toHaveTextContent("Needs you");
  expect(lnk(/PayNow REF 4471/, tid("needs-confirmation-queue"))).toHaveAttribute("href", "/reconciliation?tab=unmatched&from=attention");
  expect(tabs().map((t) => [t.textContent, t.getAttribute("href")])).toEqual([["Needs you2", "/audit?tab=needs-you"], ["Health", "/audit?tab=health"], ["Books", "/audit?tab=books"]]); v1.unmount();
  mockAuditApi(api, { get_data_quality_health_reports_data_quality_get: AUDIT_HEALTH_A });
  const v2 = render(React.createElement(Page)); await see("Grade A · Audit-Ready"); expect(selTab()).toHaveTextContent("Health"); expect(screen.queryByTestId("needs-confirmation-queue")).toBeNull(); v2.unmount();
  mockAuditApi(api, { list_classification_suggestions_statements_classification_suggestions_get: { items: [], total: 3 } });
  const v3 = render(React.createElement(Page)); await waitFor(() => expect(selTab()).toHaveTextContent("Needs you")); v3.unmount();
  setTestUrl("/audit?tab=health"); render(React.createElement(Page)); expect(selTab()).toHaveTextContent("Health");
  act(() => setTestUrl("/audit?run_id=run-1")); expect(selTab()).toHaveTextContent("Needs you");
  expect(hdg("Review this reconciliation run")).toBeInTheDocument();
  expect(tabs().map((t) => t.getAttribute("href"))).toEqual(["/audit?tab=needs-you&run_id=run-1", "/audit?tab=health&run_id=run-1", "/audit?tab=books&run_id=run-1"]);
}
export async function assertAuditOpenLoading(api: AnyMock, Page: React.ComponentType, key: readonly unknown[]) {
  for (const [op, settled] of [["reconciliation_stats_reconciliation_stats_get", auditStats(0)], ["get_workflow_status_endpoint_workflow_status_get", auditWf("ready")]] as const) {
    const { promise, resolve } = deferred(); mockAuditApi(api, { get_data_quality_health_reports_data_quality_get: AUDIT_HEALTH_A, [op]: promise });
    setTestUrl("/audit?tab=health"); const { c, w } = qcWrap(); const v = render(React.createElement(Page), w);
    await waitFor(() => expect(c.getQueryCache().findAll({ queryKey: key })[0]?.state.status).toBe("success"));
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(txt("Checking account balances and monthly statement coverage...")).toBeInTheDocument(); noTxt(/Audit[- ]Ready/i);
    await act(async () => { resolve(settled); await promise; }); await see("Grade A · Audit-Ready"); v.unmount();
  }
  api.mockImplementation((async (op: string) => (op === "get_data_quality_health_reports_data_quality_get" ? AUDIT_HEALTH_A : op === "reconciliation_stats_reconciliation_stats_get" ? Promise.reject(new Error("off")) : { items: [] })) as never);
  render(React.createElement(Page));
  expect(await screen.findByText("Open items remain", {}, { timeout: 3000 })).toBeInTheDocument();
  expect(allTxt(/The open items could not be read/).length).toBeGreaterThan(0);
}
export function assertFilterBounds(readFn: (p: URLSearchParams, d: Date, c: never) => unknown, presets: Record<string, string>) {
  expect(readFn(new URLSearchParams(""), RF_TODAY, { start: "2025-01-01", limitingAccounts: ["OCBC Bank"], latestStatementEnd: "2025-03-31" } as never)).toMatchObject({ startDate: "2025-11-01", opensAtCoverageStart: false, latestStatementEnd: "2025-03-31" });
  expect(readFn(new URLSearchParams("period=All"), RF_TODAY, { start: "2025-09-01", earliestStart: "2025-01-01", limitingAccounts: ["Harbour Bank"], latestStatementEnd: "2025-12-31" } as never)).toMatchObject({ startDate: "2025-01-01", opensAtCoverageStart: true });
  for (const none of RF_NONE_COVS) {
    expect(readFn(new URLSearchParams(""), RF_TODAY, none as never)).toMatchObject({ startDate: "2025-11-01", opensAtCoverageStart: false });
    expect(readFn(new URLSearchParams("period=All"), RF_TODAY, none as never)).toMatchObject({ startDate: "2000-01-01", openingDate: null, opensAtCoverageStart: false });
  }
  void presets;
}
export async function assertCockpitTabsAndSeries(api: AnyMock & { mock: { calls: unknown[][] } }, Page: React.ComponentType) {
  setTestUrl("/reports?tab=income-statement&period=1M&end=2026-03-31&currency=USD");
  const v1 = render(React.createElement(Page)); const tablist = screen.getByRole("tablist", { name: "Report tabs" });
  expect(within(tablist).getAllByRole("tab").map((t) => t.textContent)).toEqual(COCKPIT_TABS);
  expect(within(tablist).getByRole("tab", { name: "Income statement" })).toHaveAttribute("aria-selected", "true");
  for (const [n, h] of [["Overview", "/reports?period=1M&end=2026-03-31&currency=USD"], ["Cash flow", "/reports?period=1M&end=2026-03-31&currency=USD&tab=cash-flow"], ["Full package", "/reports?period=1M&end=2026-03-31&currency=USD&tab=package"]] as const) expect(within(tablist).getByRole("tab", { name: n })).toHaveAttribute("href", h);
  expect(await fHdg("Income Statement")).toBeInTheDocument();
  await wfCall(api, "income_statement_reports_income_statement_get", expect.objectContaining({ query: expect.objectContaining({ start_date: "2026-03-01", end_date: "2026-03-31", currency: "USD" }) }));
  expect(screen.queryByLabelText("Include restricted holdings")).toBeNull(); v1.unmount();
  const { promise: cov, resolve: rel } = deferred();
  api.mockImplementation(((op: string) => op === "report_coverage_reports_coverage_get" ? cov : op === "balance_sheet_reports_balance_sheet_get" ? Promise.resolve(COCKPIT_BS) : Promise.resolve({ currency: "SGD", granularity: "monthly", points: [] })) as never);
  setTestUrl("/reports?tab=balance-sheet&end=2026-10-22"); render(React.createElement(Page));
  expect(await fHdg("Balance Sheet")).toBeInTheDocument(); has(["Assets = Liabilities + Equity", "✓ Balanced"]); expect(lbl("Include restricted holdings")).toBeChecked();
  const series = () => api.mock.calls.filter(([id]) => id === "net_worth_timeseries_reports_net_worth_timeseries_get");
  expect(series()).toEqual([]);
  await act(async () => { rel({ as_of_date: "2026-10-22", coverage_start: "2026-07-01", limiting_accounts: ["OCBC Bank"] }); await cov; });
  await waitFor(() => expect(series()).toHaveLength(1));
  expect(series()[0][1]).toMatchObject({ query: { from: "2026-07-01", to: "2026-10-22" } });
}
export async function assertCockpitEdges(api: AnyMock & { mockReset: () => void; mockRejectedValue: (e: unknown) => unknown }, Page: React.ComponentType) {
  mockCockpitApi(api, () => new Promise(() => undefined));
  const v1 = render(React.createElement(Page)); expect(reg("Report readiness cockpit")).toHaveTextContent("Checking report readiness"); v1.unmount();
  mockCockpitApi(api, () => Promise.reject(new Error("readiness down")));
  const v2 = render(React.createElement(Page)); await see("Readiness unavailable"); expect(lnk("Open report package")).toHaveAttribute("href", "/reports?tab=package"); v2.unmount();
  mockCockpitApi(api, () => Promise.resolve(normalizablePackageDocument({ readiness: { ...COCKPIT_READINESS, action_href: "/reports/package" } })));
  setTestUrl("/reports?period=1M&currency=USD");
  const v3 = render(React.createElement(Page)); expect(await fLnk("Resolve report blockers")).toHaveAttribute("href", "/reports?period=1M&currency=USD&tab=package"); v3.unmount();
  setTestUrl("/reports"); mockCockpitApi(api, () => Promise.resolve(normalizablePackageDocument({ readiness: COCKPIT_READY })));
  const v4 = render(React.createElement(Page)); const cockpit = await fReg("Report readiness cockpit");
  await waitFor(() => expect(cockpit).toHaveTextContent("0 unconfirmed items"));
  expect(cockpit).toHaveTextContent("All inputs in this report package are confirmed."); expect(cockpit).toHaveTextContent("No blockers reported."); v4.unmount();
  api.mockReset(); api.mockRejectedValue(new Error("offline"));
  render(React.createElement(Page)); await see("Readiness unavailable"); await see("Statements unavailable: offline"); expect(allTxt("No data for this period.")).toHaveLength(3);
}

// --- Batch 3 helpers: Home, CashFlow, Workflow, BalanceSheet, Portfolio, Package ---
export const homeCard = (id: string) => within(screen.getByTestId(`cockpit-card-${id}`));
export async function assertHomeLoadingRetry(api: AnyMock, Page: React.ComponentType) {
  const p = () => new Promise(() => undefined);
  mockHomeApi(api, { balance_sheet_reports_balance_sheet_get: p, income_statement_reports_income_statement_get: p, cash_flow_reports_cash_flow_get: p });
  const v1 = render(React.createElement(Page));
  for (const c of ["balance-sheet", "income-statement", "cash-flow"]) expect(homeCard(c).getByRole("status")).toHaveTextContent("Loading…");
  v1.unmount();
  let n = 0; mockHomeApi(api, { income_statement_reports_income_statement_get: () => (n++ === 0 ? Promise.reject(new Error("income down")) : Promise.resolve(HOME_INC)) });
  render(React.createElement(Page)); await see("Statements unavailable: income down"); clk("Retry");
  await waitFor(() => noTxt(/Statements unavailable/));
  expect(homeCard("income-statement").getByText("Net income").nextElementSibling).toHaveTextContent("+$2,300");
}
export async function assertHomeMetricsLean(api: AnyMock, Page: React.ComponentType) {
  const v1 = render(React.createElement(Page));
  await waitFor(() => expect(homeCard("balance-sheet").getByText("Net worth").nextElementSibling).toHaveTextContent("$4,000"));
  await waitFor(() => expect(homeCard("income-statement").getByText("Savings rate").nextElementSibling).toHaveTextContent("66%"));
  await waitFor(() => expect(homeCard("cash-flow").getByText("Net change").nextElementSibling).toHaveTextContent("+$2,000"));
  expect(homeCard("cash-flow").getByText("Financing").nextElementSibling).toHaveTextContent("-$300");
  await wfCall(api, "list_processing_pending_reconciliation_transfers_pending_get", expect.anything());
  expect(screen.queryByRole("region", { name: "Needs attention" })).toBeNull();
  expect(screen.queryByRole("button", { name: /Show analytics/i })).toBeNull();
  noAll(["Annualized Income", "Restricted Holdings", "Risk radar", "Recent Entries", "Unmatched Alerts"]); v1.unmount();
  mockHomeApi(api, {
    balance_sheet_reports_balance_sheet_get: () => Promise.resolve({ ...HOME_FULL_BS, assets: [], liabilities: [], total_assets: "0", total_liabilities: "0", total_equity: "0" }),
    income_statement_reports_income_statement_get: () => Promise.resolve({ ...HOME_INC, income: [], expenses: [], total_income: "0", total_expenses: "0", net_income: "0" }),
  });
  render(React.createElement(Page));
  await waitFor(() => expect(homeCard("balance-sheet").getByText("Net worth").nextElementSibling).toHaveTextContent("$0"));
  noTxt(/Largest lines/);
  await waitFor(() => expect(homeCard("income-statement").getByText("Savings rate").nextElementSibling).toHaveTextContent("—"));
}
export const HOME_BANNER_CASES = [
  ["needs_action", { type: "review_required", href: "/audit", label: "Review required", summary: "Confirm." }, "An item needs your review", "Review required", "/audit", true],
  ["blocked", { type: "resolve_blocker", href: "/journal", label: "Resolve blocker" }, "A blocker holds your reports", "Resolve blocker", "/journal", false],
  ["empty", { type: "upload", count: 0, href: "/upload" }, "Upload your first statement", "Upload statements", "/upload", false],
] as const;
export async function assertHomeQueueAndScope(api: AnyMock, Page: React.ComponentType) {
  mockHomeApi(api, {
    list_statements_statements_get: () => Promise.resolve({ items: [{ id: "s1", status: "parsed", original_filename: "dbs.pdf", confidence_score: 60 }, { id: "s2", status: "parsed", original_filename: "ocbc.pdf", confidence_score: 90 }], total: 2 }),
    suggestions_chat_suggestions_get: () => Promise.resolve({ suggestions: [], structured_suggestions: [{ basis: "Blocked.", confidence_tier: "blocked", source_refs: ["report_package.readiness"], limitation: "Review.", next_action_href: "/audit" }] }),
  });
  const v1 = render(React.createElement(Page)); const b = await fReg("Needs attention");
  expect(hdg("2 items need you", undefined, b)).toBeInTheDocument();
  expect(lnk("dbs.pdf", b)).toHaveAttribute("href", "/statements/s1?from=attention");
  expect(lnk("Open Needs you", b)).toHaveAttribute("href", "/audit?tab=needs-you");
  expect(reg("Three-statement cockpit").compareDocumentPosition(await fLbl("Advisor Brief")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy(); v1.unmount();
  mockHomeApi(api, { get_workflow_status_endpoint_workflow_status_get: () => Promise.reject(new Error("w")), suggestions_chat_suggestions_get: () => Promise.reject(new Error("s")) });
  render(React.createElement(Page));
  await waitFor(() => expect(txt("Net worth").nextElementSibling).toHaveTextContent("$4,000"));
  expect(screen.queryByRole("region", { name: "Needs attention" })).toBeNull(); expect(screen.queryByLabelText("Advisor Brief")).toBeNull();
  clkLbl("Include restricted holdings");
  await waitFor(() => expect(txt("Liquid net worth").nextElementSibling).toHaveTextContent("$2,000"));
  expect(tid("excluded-holdings-note")).toHaveTextContent("Excludes restricted and illiquid holdings:Restricted Comp $2,000");
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

export const WF_HUMANIZE_CASES = [
  ["Package section invariant failed: opening_balance_missing, cash_balance_input_missing, cash_identity_missing", "Upload a bank statement to verify opening and ending cash balances."],
  ["Package section invariant failed: opening_balance_missing", "Opening balance awaits bank statement verification."],
  ["Package section invariant failed: cash_balance_input_missing", "Ending cash balance awaits bank statement verification."],
  ["Package section invariant failed: cash_identity_missing", "Cash account balance awaits bank statement verification."],
  ["Package section invariant failed", "Statement balance check needed"], ["Ordinary", "Ordinary"], [undefined, ""], [null, ""],
] as const;
export const WF_ACTION_LINKS = [["unknown", "Open workflow", "/inbox"], ["upload", "Upload statements", "/upload"], ["review_required", "Review required", "/inbox"], ["resolve_blocker", "Resolve blocker", "/reconciliation?tab=unmatched"], ["open_report", "Open report package", "/reports/package"], ["wait", "View processing", "/inbox"]] as const;
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

export const PORT_ALLOC_CASES = [
  ["retirement_benefit", "100.00", "Retirement & Benefit Assets", true],
  ["pending", "100.00", "Loading net worth allocation...", false],
  ["error", "100.00", "Unable to load net worth allocation", false],
  ["empty", "100.00", "No allocation rows available", false],
  ["default", "not-a-number", "N/A", false],
  ["default", null, "N/A", false],
] as const;
export async function assertPortHeaderStates(api: AnyMock & { mockRejectedValue: (e: unknown) => unknown; mock: { calls: unknown[][] } }, Page: React.ComponentType) {
  api.mockImplementation(((p: string) => (p.startsWith("/api/portfolio/summary") ? Promise.resolve({}) : new Promise(() => {}))) as never);
  const v1 = render(React.createElement(Page));
  has(["Portfolio", "Update Prices", "Loading holdings..."]);
  for (const id of ["performance-card", "allocation-chart-sector", "allocation-chart-geography"]) expect(tid(id)).toBeInTheDocument(); v1.unmount();
  api.mockRejectedValue(new Error("network error")); const v2 = render(React.createElement(Page));
  await see("Failed to load holdings"); expect(txt("network error")).toBeInTheDocument();
  clk("Retry loading holdings"); await waitFor(() => expect(api.mock.calls.length).toBeGreaterThan(2)); v2.unmount();
  mockPortfolioRouter(api, []); render(React.createElement(Page));
  await see("No holdings found"); expect(screen.queryByTestId("total-portfolio-value")).not.toBeInTheDocument();
}
export async function assertPortTableFilters(api: AnyMock, Page: React.ComponentType) {
  mockPortfolioRouter(api); render(React.createElement(Page));
  await see("AAPL"); has(["IBKR", "Realized P&L YTD", "Dividend Income YTD", "investment_performance", "brokerage_statement:aapl", "Cost basis uses FIFO where available."]);
  expect(tid("total-portfolio-value")).toHaveTextContent("1,800");
  expect(allTxt("$149.00").length).toBeGreaterThanOrEqual(1); expect(allTxt("$42.50").length).toBeGreaterThanOrEqual(1);
  expect(api).toHaveBeenCalledWith("/api/portfolio/performance/report-schedule?currency=SGD");
  fireEvent.change(lbl("Portfolio as-of date"), { target: { value: "2025-01-31" } }); await wfCall(api, "/api/portfolio/holdings?as_of_date=2025-01-31");
  clkLbl("Clear portfolio as-of date"); await wfCall(api, "/api/portfolio/holdings");
  fireEvent.click(screen.getByRole("checkbox", { name: "Show disposed" })); await see("TSLA");
  expect(api).toHaveBeenCalledWith("/api/portfolio/holdings?include_disposed=true");
}
export async function assertPortDrawersAndReload(api: AnyMock & { mock: { calls: unknown[][] } }, nav: { searchParams: URLSearchParams; replace: ReturnType<typeof vi.fn> }, showToastMock: unknown, Page: React.ComponentType) {
  mockPortfolioRouter(api, [PORT_H1]); const v0 = render(React.createElement(Page));
  expect(await fLnk("AAPL")).toHaveAttribute("href", "/portfolio?ticker=AAPL");
  expect(lnk(/Update Prices/)).toHaveAttribute("href", "/portfolio?panel=prices");
  expect(lnk("Add evidence")).toHaveAttribute("href", "/portfolio?panel=evidence");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); v0.unmount();
  for (const [q, title, check] of [
    ["ticker=AAPL", "AAPL", () => expect(screen.getByRole("tab", { name: "Realized P&L" })).toBeInTheDocument()],
    ["panel=prices", "Update Market Prices", () => expect(screen.getByRole("option", { name: "AAPL" })).toBeInTheDocument()],
    ["panel=evidence&source_class=liability_statement", "Guided evidence intake", () => expect(lbl("Source class")).toHaveValue("liability_statement")],
  ] as const) {
    nav.searchParams = new URLSearchParams(q); nav.replace.mockReset();
    const view = render(React.createElement(Page)); const d = await fDlg(title); await waitFor(check);
    expect(screen.getAllByRole("dialog")).toHaveLength(1); clk("Close panel", d);
    expect(nav.replace).toHaveBeenCalledWith("/portfolio", { scroll: false }); view.unmount();
  }
  nav.searchParams = new URLSearchParams("panel=unknown"); const vUnk = render(React.createElement(Page));
  await fLnk("AAPL"); expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); vUnk.unmount();
  nav.searchParams = new URLSearchParams("panel=prices"); mockPortfolioRouter(api, [PORT_H1], "100.00", "USD", "default", true);
  const reads = (pfx: string) => api.mock.calls.filter(([p]) => String(p).startsWith(pfx)).length;
  render(React.createElement(Page)); await fLnk("AAPL"); await waitFor(() => expect(reads("/api/portfolio/summary")).toBeGreaterThanOrEqual(1));
  const hB = reads("/api/portfolio/holdings"), sB = reads("/api/portfolio/summary"), sheet = dlg("Update Market Prices");
  fireEvent.change(within(sheet).getByRole("combobox"), { target: { value: "AAPL" } });
  fireEvent.change(within(sheet).getByPlaceholderText("0.00"), { target: { value: "190.50" } });
  submitForm(btn("Update Prices", sheet));
  await wfCall(nav.replace, "/portfolio", { scroll: false });
  const [, req] = api.mock.calls.find(([p]) => p === "/api/pricing/price-overrides")!;
  expect(JSON.parse(String((req as { body?: unknown }).body))).toEqual({ updates: [expect.objectContaining({ asset_identifier: "AAPL", price: "190.50" })] });
  expect(showToastMock).toHaveBeenCalledWith("Updated 1 price(s)", "success");
  await waitFor(() => expect(reads("/api/portfolio/holdings")).toBe(hB + 1)); await waitFor(() => expect(reads("/api/portfolio/summary")).toBe(sB + 1));
}
export async function assertPortAllocationLineage(api: AnyMock, Page: React.ComponentType) {
  mockPortfolioRouter(api, [PORT_H1], "100.00", "SGD");
  const { container } = render(React.createElement(Page)); const panel = await fReg("Net Worth Allocation");
  expect(api).toHaveBeenCalledWith("/api/reports/net-worth/allocation?currency=SGD&include_restricted=true");
  for (const t of ["Asset Class x Liquidity x Source Currency", "Source currency", "Net worth", "Public Equity", "Main Bank", "100.0%", "-5.0%", "2 sources", "Report currency: SGD"]) await see(t, panel);
  expect(panel).toHaveTextContent("Portfolio value shown in USD");
  expect(within(panel).queryByText(/Ties to portfolio value/)).not.toBeInTheDocument();
  expect(within(panel).queryByRole("link", { name: "AAPL market value" })).toBeNull();
  for (const l of ["AAPL market value", "Manual adjustment"]) expect(txt(l, panel).closest("li")).toHaveAttribute("title", l);
  expect(within(panel).queryByTestId("excluded-holdings-note")).toBeNull();
  fireEvent.click(within(panel).getByRole("checkbox", { name: "Include restricted holdings in allocation" }));
  await wfCall(api, "/api/reports/net-worth/allocation?currency=SGD&include_restricted=false");
  await see("Liquid net worth", panel);
  expect(tid("excluded-holdings-note", panel)).toHaveTextContent("Excludes restricted and illiquid holdings:Restricted Comp SGD 500.00");
  await fClk("View source transactions for Main Bank", panel); await see("Salary deposit");
  expect(api).toHaveBeenCalledWith(expect.stringMatching(/^\/api\/reports\/account-lineage\?account_id=acc1&/));
  expect(Array.from(container.querySelectorAll("a")).map((a) => a.getAttribute("href") ?? "").filter((h) => h.startsWith("/reports/account-lineage") || h.startsWith("/assets/"))).toEqual([]);
}

// --- PersonalReportPackagePage test-flow helpers ---
export const pkgFw = async (b = "US-like") => fireEvent.click(await fBtn(b));
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

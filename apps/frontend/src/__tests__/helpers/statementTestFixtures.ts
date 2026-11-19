import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { MouseEventHandler, ReactNode } from "react";
import React from "react";
import { expect, vi } from "vitest";
import type { apiOperation } from "@/lib/api";
import type { Schemas } from "@/lib/api-schema";
import { LEDGER_DERIVED_QUERY_KEYS } from "@/lib/queryClient";
import { createInvalidationProbe } from "../fixtures/invalidationProbe";
export { renderReviewComponent as rRev } from "./renderReviewComponent";
import type {
  Account,
  BankStatement,
  BankStatementTransaction,
  ConsistencyCheck,
  JournalEntryResponse,
  JournalLine,
  ManualValuationSnapshot,
  ManualValuationSnapshotListResponse,
  PendingMatch,
  StatementRun,
} from "@/lib/types";

type ApiMock = ReturnType<typeof vi.mocked<typeof apiOperation>>;
type ReqArg = { path?: Record<string, unknown>; query?: Record<string, unknown>; body?: unknown; signal?: AbortSignal };

export const OP = {
  STMT: "get_statement_statements__statement_id__get",
  REV: "get_statement_for_review_statements__statement_id__review_get",
  PEND_REV: "list_pending_review_statements_pending_review_get",
  CONFLICTS: "get_review_conflicts_statements__statement_id__conflicts_get",
  RESOLVE_CONF: "resolve_review_conflicts_statements__statement_id__conflict_resolutions_post",
  RUNS: "list_statement_runs_statements__statement_id__runs_get",
  RUN_POST: "create_statement_run_statements__statement_id__runs_post",
  APPROVE: "approve_statement_stage1_statements__statement_id__approvals_post",
  REJECT: "reject_statement_stage1_statements__statement_id__rejections_post",
  CONFIRM: "confirm_statement_review_envelope_statements__statement_id__review_envelopes_post",
  CORR: "create_correction_statements_corrections_post",
  DEL_STMT: "delete_statement_statements__statement_id__delete",
  ACCTS: "list_accounts_accounts_get",
  ACCT_POST: "create_account_accounts_post",
  IMPORT: "import_brokerage_positions_portfolio_brokerage_imports_post",
  STMTS: "list_statements_statements_get",
  WF_STAT: "get_workflow_status_endpoint_workflow_status_get",
  WF_EVT: "list_workflow_events_endpoint_workflow_events_get",
  XFER_PEND: "list_processing_pending_reconciliation_transfers_pending_get",
  COV: "list_statement_coverage_statements_coverage_get",
  S2_Q: "get_stage2_review_queue_reconciliation_review_queue_get",
  S2_CHK: "list_consistency_checks_reconciliation_consistency_checks_get",
  S2_SUM: "get_processing_summary_reconciliation_transfers_summary_get",
  S2_BATCH: "batch_update_matches_reconciliation_matches_post",
  S2_RES: "resolve_consistency_check_reconciliation_consistency_checks__check_id__resolutions_post",
  WB_STAT: "reconciliation_stats_reconciliation_stats_get",
  WB_PEND: "pending_review_queue_reconciliation_pending_get",
  WB_ANOM: "list_anomalies_reconciliation_transactions__txn_id__anomalies_get",
  WB_RUN: "run_reconciliation_reconciliation_runs_post",
  WB_MATCH: "update_match_decision_reconciliation_matches__match_id__patch",
  UNM_LIST: "list_unmatched_reconciliation_unmatched_get",
  UNM_POST: "submit_unmatched_reviewed_disposition_reconciliation_unmatched__txn_id__reviewed_dispositions_post",
  VAL_LIST: "list_manual_valuations_pricing_manual_valuations_get",
  VAL_POST: "create_manual_valuation_pricing_manual_valuations_post",
  AI_FB: "create_classification_feedback_statements_classification_feedback_post",
  SET_GET: "get_current_user_settings_users_me_settings_get",
  SET_PATCH: "patch_current_user_settings_users_me_settings_patch",
  LIN: "get_evidence_lineage_statements_evidence_lineage_get",
  BS: "balance_sheet_reports_balance_sheet_get",
  IS: "income_statement_reports_income_statement_get",
  CF: "cash_flow_reports_cash_flow_get",
  PORT_SUM: "get_portfolio_summary_portfolio_summary_get",
  PORT_HOLD: "get_holdings_portfolio_holdings_get",
} as const;

const q = (r?: HTMLElement) => (r ? within(r) : screen);
export const ren = render;
export const hasC = (fn: unknown, ...a: unknown[]) => expect(fn).toHaveBeenCalledWith(...a);
export const cN = (fn: unknown, n: number) => expect(fn).toHaveBeenCalledTimes(n);
export const hasCls = (el: Element | null, ...c: string[]) => expect(el).toHaveClass(...c);
export const noCls = (el: Element | null, ...c: string[]) => expect(el).not.toHaveClass(...c);
export const hasAttr = (el: Element | null, k: string, v?: string) => (v === undefined ? expect(el).toHaveAttribute(k) : expect(el).toHaveAttribute(k, v));
export const btn = (n: string | RegExp, r?: HTMLElement) => q(r).getByRole("button", { name: n });
export const fBtn = (n: string | RegExp, r?: HTMLElement) => q(r).findByRole("button", { name: n });
export const qBtn = (n: string | RegExp, r?: HTMLElement) => q(r).queryByRole("button", { name: n });
export const noBtn = (n: string | RegExp, r?: HTMLElement) => expect(qBtn(n, r)).toBeNull();
export const clk = (n: string | RegExp, r?: HTMLElement) => fireEvent.click(btn(n, r));
export const fClk = async (n: string | RegExp, r?: HTMLElement) => fireEvent.click(await fBtn(n, r));
export const chg = (l: string | RegExp, value: string, r?: HTMLElement) => fireEvent.change(q(r).getByLabelText(l), { target: { value } });
export const fChg = async (l: string | RegExp, value: string, r?: HTMLElement) => fireEvent.change(await q(r).findByLabelText(l), { target: { value } });
export const chgEl = (el: HTMLElement, value: string) => fireEvent.change(el, { target: { value } });
export const lbl = (l: string | RegExp, r?: HTMLElement) => q(r).getByLabelText(l);
export const fLbl = (l: string | RegExp, r?: HTMLElement) => q(r).findByLabelText(l);
export const qLbl = (l: string | RegExp, r?: HTMLElement) => q(r).queryByLabelText(l);
export const noLbl = (l: string | RegExp, r?: HTMLElement) => expect(qLbl(l, r)).toBeNull();
export const txt = (t: string | RegExp, r?: HTMLElement) => q(r).getByText(t);
export const fTxt = (t: string | RegExp, r?: HTMLElement) => q(r).findByText(t);
export const allTxt = (t: string | RegExp, r?: HTMLElement) => q(r).getAllByText(t);
export const fAllTxt = (t: string | RegExp, r?: HTMLElement) => q(r).findAllByText(t);
export const tid = (id: string, r?: HTMLElement) => q(r).getByTestId(id);
export const fTid = (id: string, r?: HTMLElement) => q(r).findByTestId(id);
export const dlg = (n: string | RegExp) => screen.findByRole("dialog", { name: n });
export const noDlg = (n?: string | RegExp) => expect(n ? screen.queryByRole("dialog", { name: n }) : screen.queryByRole("dialog")).toBeNull();
export const alrt = (r?: HTMLElement) => q(r).getByRole("alert");
export const fAlrt = (r?: HTMLElement) => q(r).findByRole("alert");
export const noAlrt = (r?: HTMLElement) => expect(q(r).queryByRole("alert")).toBeNull();
export const lnk = (n: string | RegExp, r?: HTMLElement) => q(r).getByRole("link", { name: n });
export const fLnk = (n: string | RegExp, r?: HTMLElement) => q(r).findByRole("link", { name: n });
export const hasLnk = (n: string | RegExp, href: string, r?: HTMLElement) => expect(lnk(n, r)).toHaveAttribute("href", href);
export const fHasLnk = async (n: string | RegExp, href: string, r?: HTMLElement) => expect(await fLnk(n, r)).toHaveAttribute("href", href);
export const stRole = (r?: HTMLElement) => q(r).getByRole("status");
export const fStRole = (r?: HTMLElement) => q(r).findByRole("status");
export const box = (r?: HTMLElement) => q(r).getByRole("textbox");
export const has = (items: (string | RegExp)[], r?: HTMLElement) => { for (const x of items) expect(txt(x, r)).toBeInTheDocument(); };
export const see = async (t: string | RegExp, r?: HTMLElement) => expect(await fTxt(t, r)).toBeInTheDocument();
export const noTxt = (t: string | RegExp, r?: HTMLElement) => expect(q(r).queryByText(t)).toBeNull();
export const dis = (n: string | RegExp, r?: HTMLElement) => expect(btn(n, r)).toBeDisabled();
export const en = (n: string | RegExp, r?: HTMLElement) => expect(btn(n, r)).toBeEnabled();
export const wFor = waitFor;
export const tick = async (ms: number) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); };
export const callsOf = (api: ApiMock, op: string) => api.mock.calls.filter(([id]) => id === op);
export const cnt = (api: ApiMock, op: string) => callsOf(api, op).length;
export const esc = () => fireEvent.keyDown(document, { key: "Escape" });
export const sub = (el: Element) => fireEvent.submit(el.closest("form")!);
export const selOpt = (el: HTMLElement, v: string) => userEvent.selectOptions(el, v);
export const wCall = (fn: unknown, ...args: unknown[]) => waitFor(() => expect(fn).toHaveBeenCalledWith(...args));
export const hasOp = (api: ApiMock, op: string, part: Record<string, unknown>) => expect(api).toHaveBeenCalledWith(op, expect.objectContaining(part));
export const wOp = (api: ApiMock, op: string, part: Record<string, unknown>) => waitFor(() => hasOp(api, op, part));
export const qRunId = (api: ApiMock, op: string = OP.S2_Q) => (api.mock.calls.find(([id]) => id === op)?.[1] as { query?: { run_id?: unknown } } | undefined)?.query?.run_id;
export const role = (r: string, n?: string | RegExp, c?: HTMLElement) => q(c).getByRole(r as never, n ? { name: n } : undefined);
export const fRole = (r: string, n?: string | RegExp, c?: HTMLElement) => q(c).findByRole(r as never, n ? { name: n } : undefined);
export const qRole = (r: string, n?: string | RegExp, c?: HTMLElement) => q(c).queryByRole(r as never, n ? { name: n } : undefined);
export const noRole = (r: string, n?: string | RegExp, c?: HTMLElement) => expect(qRole(r, n, c)).toBeNull();
export const valIs = (el: HTMLElement, v: string) => expect(el).toHaveValue(v);
export const wValIs = (el: HTMLElement | (() => HTMLElement), v: string) => waitFor(() => valIs(typeof el === "function" ? el() : el, v));
export const txtIs = (el: HTMLElement, t: string | RegExp) => expect(el).toHaveTextContent(t);
export const eq = (a: unknown, b: unknown) => expect(a).toEqual(b);
export const mObj = (a: unknown, b: Record<string, unknown>) => expect(a).toMatchObject(b);
export const wDis = (n: string | RegExp, r?: HTMLElement) => waitFor(() => dis(n, r));
export const wEn = (n: string | RegExp, r?: HTMLElement) => waitFor(() => en(n, r));
export const wNoTxt = (t: string | RegExp, r?: HTMLElement) => waitFor(() => noTxt(t, r));
export const wCnt = (api: ApiMock, op: string, n: number) => waitFor(() => expect(cnt(api, op)).toBe(n));
export const wGt = (api: ApiMock, op: string, n: number) => waitFor(() => expect(cnt(api, op)).toBeGreaterThan(n));
export async function rejectFlow(note: string) {
  await fClk("Reject");
  const d = await dlg("Reject Statement");
  chgEl(box(d), note);
  clk("Reject", d);
  return d;
}

export function deferred<T>() {
  let resolve!: (v: T) => void, reject!: (e?: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

export function memStorage(): Storage {
  const s = new Map<string, string>();
  return { getItem: (k: string) => s.get(k) ?? null, setItem: (k: string, v: string) => { s.set(k, String(v)); }, removeItem: (k: string) => { s.delete(k); }, clear: () => { s.clear(); }, key: (i: number) => Array.from(s.keys())[i] ?? null, get length() { return s.size; } } as Storage;
}

export function mockMM(matches = true) {
  Object.defineProperty(window, "matchMedia", { configurable: true, writable: true, value: vi.fn().mockImplementation((media: string) => ({ matches, media, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), onchange: null, dispatchEvent: vi.fn() })) });
}

export const VALID_BAL = { opening_balance: "1000.00", closing_balance: "1500.00", calculated_closing: "1500.00", opening_delta: "0.00", closing_delta: "0.00", opening_match: true, closing_match: true, validated_at: "2026-01-31T00:00:00Z" };
export const EMPTY_CONFLICTS = { duplicates: [], transfer_pairs: [], resolved: true };
export const EMPTY_WF = { primary_state: "empty", next_action: { type: "upload", count: 0, href: "/upload", label: "Upload statements", summary: "Add source documents." }, report_readiness: { state: "none", blocking_count: 0, href: "/reports" }, event_counts: { unread: 0, action_required: 0, blocked: 0 } };
export const EMPTY_XFER = { pending_count: 0, pending_total: "0.00", currency: "SGD", oldest_pending_date: null };

export const mkTxn = (o: Record<string, unknown> = {}): BankStatementTransaction =>
  ({ id: "t1", statement_id: "s1", txn_date: "2026-01-10", description: "Coffee", amount: "3.50", direction: "OUT", currency: "SGD", confidence: "high", status: "pending", created_at: "", updated_at: "", ...o }) as BankStatementTransaction;

export const mkStmt = (o: Record<string, unknown> = {}): BankStatement & Record<string, unknown> =>
  ({ id: "s1", user_id: "u1", account_id: null, account_last4: null, file_path: "/tmp/s1.pdf", original_filename: "statement-jan.pdf", institution: "DBS", currency: "SGD", period_start: "2026-01-01", period_end: "2026-01-31", opening_balance: "1000", closing_balance: "1500", status: "parsed", confidence_score: 92, balance_validated: true, validation_error: null, brokerage_import_failed: false, parsing_progress: 100, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", transactions: [], ...o }) as BankStatement & Record<string, unknown>;

export const mkRun = (o: Partial<StatementRun> = {}): StatementRun =>
  ({ id: `run-${o.seq ?? 1}`, seq: 1, kind: "extract", state: "succeeded", actor_kind: "system", trigger: "upload", parent_run_id: null, hints: { keywords: [], note: null }, model: null, prompt_template_version: null, prompt_digest: null, error_code: null, error_message: null, requested_at: "2026-01-05T08:00:00Z", started_at: "2026-01-05T08:00:01Z", finished_at: "2026-01-05T08:00:30Z", ...o });

export const mkUserRun = (o: Partial<StatementRun> = {}) =>
  mkRun({ actor_kind: "user", trigger: "rerun", prompt_template_version: "1", prompt_digest: "d".repeat(64), ...o });

export const mkClassifyRun = (state: StatementRun["state"], o: Partial<StatementRun> = {}) =>
  mkRun({ seq: 2, kind: "classify", state, trigger: "auto_classify", parent_run_id: "run-1", finished_at: state === "requested" || state === "running" ? null : "2026-01-05T08:00:40Z", ...o });

export const mkMatch = (o: Partial<PendingMatch> = {}): PendingMatch =>
  ({ id: "m1", match_score: 88, confidence_tier: "HIGH", status: "pending_review", created_at: "2026-01-01T00:00:00Z", description: "Salary transfer", amount: "1200.00", txn_date: "2026-01-01", ...o });

export const mkCheck = (o: Partial<ConsistencyCheck> = {}): ConsistencyCheck =>
  ({ id: "c1", check_type: "duplicate", status: "pending", related_txn_ids: [], details: { message: "Potential duplicate" }, severity: "high", resolved_at: null, resolution_note: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", ...o });

export const mkQueue = (o: Partial<{ pending_matches: PendingMatch[]; consistency_checks: ConsistencyCheck[]; has_unresolved_checks: boolean }> = {}) =>
  ({ pending_matches: [mkMatch()], consistency_checks: [], has_unresolved_checks: false, ...o });

export const mkAcc = (o: Record<string, unknown> & { id?: string; name?: string } = {}): Account =>
  ({ id: "a1", name: "Cash", code: null, type: "ASSET", currency: "SGD", description: null, parent_id: null, is_active: true, balance: "0", is_system: false, user_id: "u1", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", ...o }) as Account;

export const mkLn = (o: Record<string, unknown> = {}): JournalLine =>
  ({ id: "l1", journal_entry_id: "je1", account_id: "a1", direction: "DEBIT", amount: "100", currency: "SGD", event_type: null, fx_rate: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", ...o }) as JournalLine;

export const mkEntry = (o: Record<string, unknown> = {}): JournalEntryResponse =>
  ({ id: "je1", user_id: "u1", decision_authority_state: "anchored", entry_date: "2023-02-02", memo: "", source_type: "manual_entry", status: "posted", lines: [mkLn()], created_at: "2023-02-02T00:00:00Z", updated_at: "2023-02-02T00:00:00Z", ...o }) as unknown as JournalEntryResponse;

export const mkBrokRes = (o: Record<string, unknown> = {}) =>
  ({ broker: "Moomoo", parsed_positions: 5, created_atomic_positions: 3, existing_atomic_positions: 2, reconcile_created: 3, reconcile_updated: 2, reconcile_disposed: 0, skipped: 0, ...o });

export const mkHolding = (o: Record<string, unknown> = {}) =>
  ({ id: "h1", user_id: "u1", account_id: "acc1", asset_identifier: "AAPL", quantity: "10", cost_basis: "1500.00", market_value: "1800.00", unrealized_pnl: "300.00", unrealized_pnl_percent: "20.00", currency: "USD", native_cost_basis: "1500.00", native_currency: "USD", reporting_cost_basis: "1500.00", reporting_currency: "USD", acquisition_date: "2026-01-31", status: "active", account_name: "Moomoo", asset_type: "Equity", sector: "Technology", geography: "US", ...o });

export const mkPortSum = (o: Record<string, unknown> = {}) =>
  ({ total_market_value: "1800.00", total_cost_basis: "1500.00", total_unrealized_pnl: "300.00", total_unrealized_pnl_percent: "20.00", total_realized_pnl: "0.00", total_realized_pnl_percent: "0.00", net_pnl: "300.00", net_pnl_percent: "20.00", holdings_count: 1, active_positions_count: 1, disposed_positions_count: 0, currency: "USD", realized_pnl_ytd: "0.00", dividend_income_ytd: "0.00", ...o });

export const mkSnap = (o: Record<string, unknown> = {}): ManualValuationSnapshot =>
  ({ id: "s1", user_id: "u1", component_type: "rsu", liquidity_class: "restricted", as_of_date: "2026-05-18", value: "12500.00", currency: "USD", source: "Acme RSU grant (grant-2026.pdf p3)", valuation_basis: "employer_grant_document", notes: null, provenance: "manual", created_at: "2026-05-18T00:00:00Z", updated_at: "2026-05-18T00:00:00Z", ...o }) as ManualValuationSnapshot;

export const BASE_EV_FORM = { source_class: "property_statement" as const, value: "300000", currency: "SGD", as_of_date: "2026-01-01", valuation_basis: "market_appraisal" as const, source_label: "Condo appraisal", source_anchor: "", notes: "" };

export const AI_MODELS = [{ id: "google/gemini-3-flash-preview", name: "Gemini 3 Flash", is_free: true }, { id: "qwen/qwen-2.5-vl-7b-instruct:free", name: "Qwen 2.5 VL 7B", is_free: true }];

export const WB_STATS = { total_transactions: 5, matched_transactions: 2, unmatched_transactions: 3, pending_review: 2, auto_accepted: 1, match_rate: 40, score_distribution: { high: 1, medium: 2, low: 2 } };
export const WB_MATCH = { id: "m1", match_score: 85, status: "pending_review", transaction: { id: "t1", description: "Rent", txn_date: "2026-01-02", direction: "OUT", amount: 800 }, entries: [{ id: "e1", memo: "Rent", entry_date: "2026-01-02", total_amount: 800 }], score_breakdown: { amount: 50, date: 20, description: 15 } };

export const UNM_ITEM = { id: "u1", statement_id: "s1", txn_date: "2026-01-11", description: "Card payment", amount: "88.00", currency: "SGD", direction: "OUT", status: "unmatched" };
export const UNM_EXP = { id: "expense-1", name: "Expense - Dining", type: "EXPENSE", currency: "SGD", is_active: true };

export const mkSug = (suggestion_id: string, transaction: string, suggested_category_or_match = "DINING", extra: Record<string, unknown> = {}) =>
  ({ suggestion_id, transaction, suggested_category_or_match, ai_score: 72, ai_reasoning: "Merchant name indicates dining.", ...extra });

export const nd = (id: string, node_kind: string, entity_type: string, entity_id: string, properties: Record<string, unknown> = {}) => ({ id, node_kind, entity_type, entity_id, properties });
export const ed = (id: string, relation: string, direction: string, depth: number, from_node_id: string, to_node_id: string) => ({ id, relation, direction, depth, from_node_id, to_node_id, properties: {} });
export const setLin = (api: ApiMock, nodes: unknown[], edges: unknown[] = [], blockers: unknown[] = []) =>
  api.mockResolvedValue({ anchor: null, max_depth: 6, blockers, edges, nodes } as never);

export function mockStmtApi(api: ApiMock, opts: { stmt?: unknown | (() => unknown); rev?: unknown | (() => unknown); runs?: StatementRun[] | (() => StatementRun[]); pend?: unknown; conflicts?: unknown; extra?: (op: string, req?: ReqArg) => Promise<unknown> | undefined } = {}) {
  const getS = () => (typeof opts.stmt === "function" ? (opts.stmt as () => unknown)() : opts.stmt ?? mkStmt());
  api.mockImplementation(((op: string, req?: ReqArg) => {
    const c = opts.extra?.(op, req);
    if (c !== undefined) return c as never;
    if (op === OP.STMT) return Promise.resolve(getS()) as never;
    if (op === OP.REV) {
      const r = typeof opts.rev === "function" ? (opts.rev as () => unknown)() : opts.rev;
      return Promise.resolve(r ?? { ...(getS() as Record<string, unknown>), balance_validation_result: VALID_BAL, source_missing_facts: [], source_envelope_reviewable: false, reviewed_envelope: null }) as never;
    }
    if (op === OP.PEND_REV) return Promise.resolve(opts.pend ?? { items: [{ id: "s1" }], total: 1 }) as never;
    if (op === OP.CONFLICTS) return Promise.resolve(opts.conflicts ?? EMPTY_CONFLICTS) as never;
    if (op === OP.RUNS) { const items = typeof opts.runs === "function" ? opts.runs() : (opts.runs ?? []); return Promise.resolve({ items, total: items.length }) as never; }
    return Promise.reject(new Error(`Unexpected operation ${op}`)) as never;
  }) as unknown as typeof apiOperation);
}

export function mockStmtsPageApi(api: ApiMock, opts: { statements?: unknown[]; deletes?: unknown[]; workflowStatus?: unknown; workflowEvents?: unknown; pendingTransfers?: unknown; statementCoverage?: unknown; extra?: (op: string, req?: ReqArg) => Promise<unknown> | undefined } = {}) {
  const sq = [...(opts.statements ?? [{ items: [] }])], dq = [...(opts.deletes ?? [])];
  const pop = (q: unknown[], fb: unknown) => { const n = q.length ? q.shift() : fb; return n instanceof Error ? Promise.reject(n) : Promise.resolve(n); };
  api.mockImplementation(((op: string, req?: ReqArg) => {
    const c = opts.extra?.(op, req);
    if (c !== undefined) return c as never;
    if (op === OP.STMTS) return pop(sq, { items: [] }) as never;
    if (op === OP.WF_STAT) return Promise.resolve(opts.workflowStatus ?? EMPTY_WF) as never;
    if (op === OP.WF_EVT) return Promise.resolve(opts.workflowEvents ?? { total: 0, items: [], sessions: [] }) as never;
    if (op === OP.XFER_PEND) return Promise.resolve(opts.pendingTransfers ?? { items: [], total: 0 }) as never;
    if (op === OP.COV) return Promise.resolve(opts.statementCoverage ?? { items: [], total: 0, as_of: "2026-05-01" }) as never;
    if (op === OP.DEL_STMT) return pop(dq, undefined) as never;
    return Promise.reject(new Error(`Unexpected api call: ${op}`)) as never;
  }) as unknown as typeof apiOperation);
}

export function mockStage2Api(api: ApiMock, opts: { queue?: unknown | (() => Promise<unknown>); summary?: unknown | Promise<unknown> | (() => Promise<unknown>); checks?: readonly unknown[] | (() => Promise<unknown>); extra?: (op: string, req?: ReqArg) => Promise<unknown> | undefined } = {}) {
  api.mockImplementation(((op: string, req?: ReqArg) => {
    const c = opts.extra?.(op, req);
    if (c !== undefined) return c as never;
    if (op === OP.S2_Q) return (typeof opts.queue === "function" ? (opts.queue as () => Promise<unknown>)() : Promise.resolve(opts.queue ?? mkQueue())) as never;
    if (op === OP.S2_SUM) return (typeof opts.summary === "function" ? (opts.summary as () => Promise<unknown>)() : opts.summary instanceof Promise ? opts.summary : Promise.resolve(opts.summary ?? EMPTY_XFER)) as never;
    if (op === OP.S2_CHK) return (typeof opts.checks === "function" ? (opts.checks as () => Promise<unknown>)() : Promise.resolve({ items: opts.checks ?? [] })) as never;
    if (op === OP.S2_RES) return Promise.resolve({ success: true }) as never;
    if (op === OP.S2_BATCH) return Promise.resolve((req?.body as { action?: string } | undefined)?.action === "reject" ? { success: true, rejected_count: 1 } : { success: true, approved_count: 1 }) as never;
    return Promise.reject(new Error(`Unexpected operation ${op}`)) as never;
  }) as unknown as typeof apiOperation);
}

export function mockWbApi(api: ApiMock, ov: Record<string, (req?: ReqArg) => Promise<unknown>> = {}) {
  api.mockImplementation(((op: string, req?: ReqArg) => {
    if (ov[op]) return ov[op](req) as never;
    if (op === OP.WB_STAT) return Promise.resolve(WB_STATS) as never;
    if (op === OP.WB_PEND) return Promise.resolve({ items: [WB_MATCH] }) as never;
    if (op === OP.WB_ANOM) return Promise.resolve([]) as never;
    return Promise.resolve({}) as never;
  }) as unknown as typeof apiOperation);
}

export function mockValApi(api: ApiMock, list: ManualValuationSnapshotListResponse = { items: [], total: 0 }, post?: Promise<unknown>) {
  api.mockImplementation(((op: string) => {
    if (op === OP.VAL_LIST) return Promise.resolve(list) as never;
    if (op === OP.VAL_POST) return (post ?? Promise.resolve(mkSnap())) as never;
    return Promise.reject(new Error(`Unexpected ${op}`)) as never;
  }) as unknown as typeof apiOperation);
}

export const COCKPIT_BS = { as_of_date: "2026-06-30", currency: "USD", assets: [], liabilities: [], equity: [], total_assets: "100", total_liabilities: "0", total_equity: "100", equation_delta: "0", is_balanced: true, opening_balance_warnings: [{ message: "Record opening balances." }] };

export function mockCockpitApi(api: ApiMock, ov: Record<string, () => Promise<unknown>> = {}) {
  api.mockImplementation(((op: string) => {
    if (ov[op]) return ov[op]() as never;
    if (op === OP.BS) return Promise.resolve(COCKPIT_BS) as never;
    if (op === OP.IS) return Promise.resolve({ currency: "USD", income: [], expenses: [], total_income: "0", total_expenses: "0", net_income: "0", trends: [] }) as never;
    if (op === OP.CF) return Promise.resolve({ currency: "USD", operating: [], investing: [], financing: [], summary: {} }) as never;
    return Promise.reject(new Error(`unexpected ${op}`)) as never;
  }) as unknown as typeof apiOperation);
}

export const WF_DATA = {
  workflowStatus: { primary_state: "needs_action", next_action: { type: "review_required", count: 1, href: "/statements/s1", label: "Review required", summary: "Confirm." }, report_readiness: { state: "blocked", blocking_count: 1, href: "/reports/package" }, event_counts: { unread: 1, action_required: 1, blocked: 0 } },
  workflowEvents: { total: 1, items: [{ id: "e1", user_id: "u1", session_id: "ses1", occurred_at: "2026-03-02T00:00:00Z", family: "bank_statement.action_required", severity: "action_required", status: "unread", title: "March statement needs review", summary: "Rows wait.", source_type: "bank_statement", source_id: "s1", action_href: "/statements/s1", report_impact: "blocked", dedupe_key: "event:e1", created_at: "2026-03-02T00:00:00Z", updated_at: "2026-03-02T00:00:00Z" }], sessions: [{ id: "ses1", status: "active", title: "Session", summary: "Work.", started_at: "2026-03-01T00:00:00Z", last_event_at: "2026-03-02T00:00:00Z", source_count: 1, primary_state: "needs_action", report_readiness: { state: "blocked", blocking_count: 1, href: "/reports/package" }, event_counts: { unread: 1, action_required: 1, blocked: 0 } }] },
  pendingTransfers: { items: [{ entry_id: "t1", from_account: "DBS Savings", to_account: "OCBC Current", amount: "250.00", currency: "SGD", initiated_date: "2026-03-05", days_outstanding: 10, description: "Move" }], total: 1 },
  statementCoverage: { as_of: "2026-05-10", total: 2, items: [{ account_id: "acc-1", account_name: "DBS Checking", currency: "SGD", cadence: "monthly", latest_source_date: "2026-04-30", latest_confirmed_balance: "1200.50", stale_after_days: 45, is_stale: false, has_daily_snapshot_override: false, coverage_complete: true, issues: [] }, { account_id: "acc-2", account_name: "OCBC Savings", currency: "SGD", cadence: "monthly", latest_source_date: "2026-02-28", latest_confirmed_balance: "300.00", stale_after_days: 45, is_stale: true, has_daily_snapshot_override: false, coverage_complete: false, issues: [{ type: "gap", severity: "warning", currency: "SGD", period_start: "2026-03-01", period_end: "2026-03-31" }] }] },
};

export const COCKPIT_QUERIES: unknown[] = [
  [OP.BS, { as_of_date: "2026-06-30", currency: "USD", include_restricted: true }],
  [OP.BS, { as_of_date: "2025-12-31", currency: "USD", include_restricted: true }],
  [OP.IS, { start_date: "2026-01-01", end_date: "2026-06-30", currency: "USD" }],
  [OP.CF, { start_date: "2026-01-01", end_date: "2026-06-30", currency: "USD" }],
];

export const COCKPIT_CF_EMPTY = { currency: "USD", operating: [], investing: [], financing: [], summary: {} };

export const COCKPIT_NORM = {
  is: { currency: "SGD", income: [], expenses: [], total_income: "0", total_expenses: "0", net_income: "0" },
  cf: { currency: "USD", operating: [], investing: [], financing: [], summary: { operating_activities: "0", investing_activities: "0", financing_activities: "0", net_cash_flow: "12.50" } },
};

export const navReconMock = () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }), useSearchParams: () => new URLSearchParams(), usePathname: () => "/reconciliation" });
export const S2_DUP = mkCheck({ details: { message: "Duplicate transfer" } });
export const S2_Q = mkQueue({ pending_matches: [mkMatch({ description: "Transfer", amount: "20", txn_date: "2024-01-03" })] });

export const s2MatchClick = async (name: string | RegExp = "Salary transfer") => {
  fireEvent.click(within(await fTid("stage2-desktop-match-region")).getByText(name));
};

export const s2Resolve = async (action: string | RegExp, note: string) => {
  clk("Resolve");
  const d = await dlg("Resolve Consistency Check");
  chgEl(box(d), note);
  clk(action, d);
  return d;
};

export const HistoryLink = ({ href, children, onClick, scroll: _s, prefetch: _p, replace: _rp, ...r }: { href: string; children: ReactNode; onClick?: MouseEventHandler<HTMLAnchorElement>; scroll?: boolean; prefetch?: boolean; replace?: boolean; [k: string]: unknown }) =>
  React.createElement("a", {
    href,
    onClick: (e: React.MouseEvent<HTMLAnchorElement>) => {
      onClick?.(e);
      if (!e.defaultPrevented && href.startsWith("/")) {
        e.preventDefault();
        window.history.pushState({}, "", href);
        window.dispatchEvent(new Event("popstate"));
      }
    },
    ...r,
  }, children);

export function mockBrokRouteApi(api: ApiMock, stmt: unknown) {
  api.mockImplementation(((op: string) => {
    if (op === OP.STMT) return Promise.resolve(stmt) as never;
    if (op === OP.IMPORT) return Promise.resolve(mkBrokRes({ parsed_positions: 1, created_atomic_positions: 1, existing_atomic_positions: 0, reconcile_created: 1, reconcile_updated: 0 })) as never;
    if (op === OP.PORT_SUM) return Promise.resolve(mkPortSum()) as never;
    if (op === OP.PORT_HOLD) return Promise.resolve({ items: [mkHolding({ acquisition_date: "2026-01-31", account_name: "Moomoo" })], total: 1, warnings: [] }) as never;
    return Promise.reject(new Error(`Unhandled ${op}`)) as never;
  }) as unknown as typeof apiOperation);
}

export const mkLinNodes = (rows: Array<[string, string, string, string, Record<string, unknown>?]>) =>
  rows.map(([id, node_kind, entity_type, entity_id, properties = {}]) => ({ id, node_kind, entity_type, entity_id, properties }));

export const mkLinEdges = (rows: Array<[string, string, string, number, string, string]>) =>
  rows.map(([id, relation, direction, depth, from_node_id, to_node_id]) => ({ id, relation, direction, depth, from_node_id, to_node_id, properties: {} }));

export const LOW_TXN = mkTxn({ id: "txn-123", statement_id: "stmt-456", txn_date: "2024-03-15", description: "Starbucks Coffee #998", amount: "5.50", confidence: "low", confidence_tier: "LOW" });

export const mkFile = (name: string, type: string, sizeOrContent: string | number = "x") =>
  new File([typeof sizeOrContent === "number" ? new Uint8Array(sizeOrContent) : sizeOrContent], name, { type });

export const mockApiSeq = (api: { mockResolvedValueOnce: (v: never) => unknown; mockRejectedValueOnce: (e: unknown) => unknown }, ...vals: unknown[]) => {
  for (const v of vals) if (v instanceof Error) api.mockRejectedValueOnce(v); else api.mockResolvedValueOnce(v as never);
};

export const atomic = (id: string, txn_date: string, description: string, amount: string, direction: "IN" | "OUT", confidence_tier: "HIGH" | "LOW", source_row: number) =>
  ({ id, statement_id: "s1", txn_date, description, amount, direction, reference: null, currency: "SGD", confidence_tier, source_row, created_at: "", updated_at: "" }) as Schemas["AtomicTransactionResponse"];

export const seedInv = (client: QueryClient, keys: readonly (readonly unknown[])[], extra: readonly unknown[] = ["unrelated"]) => {
  for (const k of [...keys, extra]) client.setQueryData(k, { seeded: true });
};

export const expectInv = (client: QueryClient, keys: readonly (readonly unknown[])[], extra: readonly unknown[] = ["unrelated"]) => {
  expect(keys.map((k) => client.getQueryState(k)?.isInvalidated)).toEqual(keys.map(() => true));
  expect(client.getQueryState(extra)?.isInvalidated).toBe(false);
};

export function setupRunApi(api: ApiMock, opts: { status?: string | (() => string); filename?: string; file_path?: string; validation_error?: string | null; runs: () => StatementRun[]; rev?: unknown | (() => unknown); post?: (b: unknown) => Promise<unknown>; reject?: (b: unknown) => Promise<unknown>; extra?: (op: string, req?: ReqArg) => Promise<unknown> | undefined }) {
  const getStatus = () => (typeof opts.status === "function" ? opts.status() : opts.status) ?? "rejected";
  const getStmt = () => mkStmt({ status: getStatus(), original_filename: opts.filename ?? "statement-jan.pdf", opening_balance: 1000, closing_balance: 1500, ...("file_path" in opts ? { file_path: opts.file_path } : {}), ...("validation_error" in opts ? { validation_error: opts.validation_error } : {}) });
  mockStmtApi(api, {
    stmt: getStmt, runs: opts.runs, pend: { items: [], total: 0 },
    rev: opts.rev ?? (() => ({ ...getStmt(), balance_validation_result: null, source_missing_facts: [], source_envelope_reviewable: false, reviewed_envelope: null })),
    extra: (op, req) => {
      const e = opts.extra?.(op, req);
      if (e !== undefined) return e;
      if (op === OP.RUN_POST) return opts.post ? opts.post(req?.body) : Promise.resolve(mkUserRun({ seq: 9 }));
      if (op === OP.REJECT) return opts.reject ? opts.reject(req?.body) : Promise.resolve({ ...getStmt(), status: "rejected" });
      return undefined;
    },
  });
}

export const REV_BAL = { ...VALID_BAL, opening_balance: "100.00", closing_balance: "120.00", calculated_closing: "120.00", validated_at: "2024-01-31T00:00:00Z" };
export const REV_STMT = mkStmt({ original_filename: "statement.pdf", period_start: "2024-01-01", period_end: "2024-01-31", opening_balance: 100, closing_balance: 120, stage1_status: null, balance_validation_result: REV_BAL, pdf_url: null, transactions: [mkTxn({ id: "txn-1", txn_date: "2024-01-03", description: "Salary", reference: "REF-1", amount: 20, direction: "IN", balance_after: 120, status: "draft" })] });
export const REV_CONFLICTS = { duplicates: [{ id: "t1", txn_date: "2025-01-15", description: "Duplicate deposit", amount: "20.00", direction: "IN" }], transfer_pairs: [{ id: "t2", txn_date: "2025-01-16", description: "Transfer to savings", amount: "20.00", direction: "OUT" }] };

export const COCKPIT_WARN = [{ message: "Record opening balances.", type: "unknown" }];
export const lN = mkLinNodes;
export const lE = mkLinEdges;
export const accP = (id: string, name: string, balance: string, o: Record<string, unknown> = {}) => mkAcc({ id, name, balance, ...o });
export const lnP = (id: string, account_id: string, direction: "DEBIT" | "CREDIT", amount: string, o: Record<string, unknown> = {}) => mkLn({ id, account_id, direction, amount, ...o });
export const brokNavMock = () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useParams: () => { const m = window.location.pathname.match(/^\/statements\/([^/]+)/); return m ? { id: m[1] } : {}; },
  useSearchParams: () => new URLSearchParams(window.location.search),
});

export async function approveStmt() {
  fireEvent.click(await fBtn("Approve"));
  clk("Approve", await dlg("Approve Statement"));
}

export const COCKPIT_QS = "period=YTD&end=2026-06-30&currency=USD&include_restricted=true";
export const S2_BATCH_CASES = [
  ["accept", /Approve Selected/i, { approved_count: 1, rejected_count: 0, journal_entries_reconciled: 1 }],
  ["reject", "Reject", { approved_count: 0, rejected_count: 1, journal_entries_reconciled: 0 }],
] as const;

export const CK = {
  qs: COCKPIT_QS,
  queries: COCKPIT_QUERIES,
  warn: COCKPIT_WARN,
  norm: COCKPIT_NORM,
  cfEmpty: COCKPIT_CF_EMPTY,
  pending: { balanceSheet: false, incomeStatement: false, cashFlow: false },
};

export const lowMoneyMock = () => ({ formatCurrencyLocale: (a: unknown, c: string) => `${c} ${String(a)}` });
export const LOW_STATES = [
  [{ isOpen: true, transaction: LOW_TXN }, ["Review Low-Confidence Transaction", "Starbucks Coffee #998", "-SGD 5.50", /2024-03-15/]],
  [{ isOpen: true, transaction: { ...LOW_TXN, direction: "IN", confidence_tier: undefined, confidence: "medium" } }, ["+SGD 5.50", "medium"]],
] as const;

export const S2_FIX = {
  dup: S2_DUP,
  q: S2_Q,
  batch: S2_BATCH_CASES,
  err409: "409 Conflict: unresolved consistency checks block batch approval",
};

export const LIN_A = { entity_type: "journal_line", entity_id: "11111111-1111-4111-8111-111111111111", node_kind: "ledger_line" } as const;

export const DETAIL_ACC = {
  cash: accP("a1", "Cash", "1000"),
  bank: accP("a2", "Bank", "200", { code: "1001", description: "Main account" }),
  wallet: accP("a3", "Wallet", "50"),
};

export function mkRouteHarness(Port: React.ComponentType, Stmt: React.ComponentType) {
  return function RouteHarness() {
    const [p, setP] = React.useState(window.location.pathname);
    React.useEffect(() => { const fn = () => setP(window.location.pathname); window.addEventListener("popstate", fn); return () => window.removeEventListener("popstate", fn); }, []);
    return React.createElement(p === "/portfolio" ? Port : Stmt);
  };
}

export const EV_FIX = {
  bad: ["abc", "0", "0.00", "-5", "-12500.50", "Infinity", "NaN", "1e3", "1,000", "  ", "12.34.56"],
  good: ["1", "0.01", "12500", "12500.50", " 300000 "],
  snaps: { items: [mkSnap(), mkSnap({ id: "s2", valuation_basis: null })], total: 2 },
};

export const CLS_MSG = {
  notice: "Classifying transactions…",
  blocked: "Wait for the active run to end before approving this statement.",
};

export function setupClassifyApi(api: ApiMock, runs: () => StatementRun[], revExtra: Record<string, unknown> = {}, post?: () => Promise<unknown>) {
  const s = mkStmt({ file_path: undefined, opening_balance: 1000, closing_balance: 1500, validation_error: "Economic review required: 2 rows need review" });
  mockStmtApi(api, {
    stmt: s, runs, pend: { items: [], total: 0 },
    rev: { ...s, reviewed_envelope: { id: "e1" }, account_id: "a1", source_missing_facts: [], source_envelope_reviewable: false, balance_validation_result: VALID_BAL, ...revExtra },
    extra: (op) => ([OP.APPROVE, OP.REJECT, OP.CONFIRM].includes(op as never) ? (post?.() ?? Promise.reject(new Error(`Unexpected ${op}`))) : undefined),
  });
}

export const AI_FIX = {
  id: "00000000-0000-0000-0000-000000000012",
  sug: (id = "00000000-0000-0000-0000-000000000012", txn = "PAYNOW TRANSFER", cat = "Expense - Food & Dining", ex: Record<string, unknown> = { direction: "OUT", ai_score: 81 }) => mkSug(id, txn, cat, ex),
  journal: { items: [{ id: "e1", entry_date: "2026-04-01", memo: "Processing transfer", source_type: "system", confidence_tier: "LOW", status: "posted", lines: [{ id: "l1", account_id: "a1", direction: "DEBIT", amount: 10, currency: "SGD" }], created_at: "2026-04-01T00:00:00Z" }], total: 1 },
  audit: { items: [{ timestamp: "2026-04-01T10:00:00Z", actor: "ai", action: "classified", old_value: { category: null }, new_value: { category: "Food & Dining" } }] },
  setBase: { enable_ai_reconciliation: true, enable_ai_classification: false, auto_accept_ai_suggestions: true, auto_accept_ai_suggestions_active: false },
};

export const TXN_FIX = {
  sample: [mkTxn({ txn_date: "2024-01-10", amount: "3.5" })],
  tiers: [mkTxn({ id: "a", confidence: "high" }), mkTxn({ id: "b", confidence: "medium" }), mkTxn({ id: "c", confidence: "low", confidence_tier: undefined }), mkTxn({ id: "d", amount: "50", direction: "IN", confidence: "low", confidence_tier: "HIGH" })],
  multi: [mkTxn({ id: "s", description: "Salary", confidence_tier: "HIGH" }), mkTxn({ id: "g", description: "Grab", confidence_tier: "MEDIUM" }), mkTxn({ id: "r", description: "Rent", confidence_tier: "TRUSTED" }), mkTxn({ id: "f", description: "Card fee", confidence_tier: "LOW" }), mkTxn({ id: "gr", description: "Groceries", confidence_tier: "HIGH" }), mkTxn({ id: "p", description: "PayNow", confidence_tier: "LOW" })],
  wire: [atomic("1", "2026-10-05", "Oct 5 low", "50.00", "OUT", "LOW", 4), atomic("2", "2026-10-15", "Oct 15 second", "20.00", "OUT", "HIGH", 3), atomic("3", "2026-10-15", "Oct 15 first low", "30.00", "OUT", "LOW", 2), atomic("4", "2026-10-25", "Oct 25 top", "100.00", "IN", "HIGH", 1)],
  unratedRaw: { id: "u", statement_id: "s1", txn_date: "2026-10-03", description: "Unrated", amount: "10.00", direction: "OUT", reference: null, currency: "SGD", created_at: "", updated_at: "" } as Schemas["AtomicTransactionResponse"],
};

export const BROK_STMT = mkStmt({ original_filename: "moomoo-2026-01.pdf", institution: "Moomoo", currency: "USD", opening_balance: null, closing_balance: null, file_path: undefined });
export const brokSummaryMock = () => ({
  PerformanceCard: () => React.createElement("div", { "data-testid": "performance-card" }),
  AllocationChart: ({ type, title }: { type: string; title: string }) => React.createElement("div", { "data-testid": `allocation-chart-${type}` }, title),
});

export const LIN_FIX = {
  flat: [lN([["n1", "ledger_line", "journal_line", "j1"], ["n2", "extracted_record", "bank_statement_transaction", "s1"], ["n3", "atomic_fact", "atomic_transaction", "a1"], ["n4", "source_document", "uploaded_document", "d1"]])] as const,
  chain: [
    lN([["l", "ledger_line", "journal_line", "j1", { source_type: "journal_entry", confidence_tier: "TRUSTED", version: "posted" }], ["r", "report_line", "balance_sheet_line", "r1"], ["s", "source_document", "uploaded_document", "d1", { source_system: "statement_upload", confidence_tier: "HIGH", version: "v3" }], ["a", "atomic_fact", "atomic_transaction", "a1", { confidence: "HIGH", record_version: 2 }]]),
    lE([["e1", "parsed_into", "upstream", 3, "s", "a"], ["e2", "posted_as", "upstream", 2, "a", "l"], ["e3", "aggregated_into", "downstream", 1, "l", "r"]]),
  ] as const,
  disc: [lN([["l", "ledger_line", "journal_line", "j1"], ["o", "source_document", "uploaded_document", "d2"], ["s", "source_document", "uploaded_document", "d1"]]), lE([["e1", "posted_as", "upstream", 1, "s", "l"]])] as const,
  cyc: [lN([["l", "ledger_line", "journal_line", "j1"], ["s", "source_document", "uploaded_document", "d1"]]), lE([["e1", "related_to", "both", 1, "l", "s"], ["e2", "derived_from", "both", 2, "s", "l"]])] as const,
  inc: [lN([["l", "ledger_line", "journal_line", "j1"]]), lE([["e1", "derived_from", "upstream", 1, "l", "missing"]])] as const,
};

export const DETAIL_JE = {
  base: mkEntry({ lines: [lnP("l1", "a1", "DEBIT", "100"), lnP("l2", "a2", "CREDIT", "100")] }),
  mob: mkEntry({ id: "je-m", lines: [lnP("ld", "assets:cash:mobile", "DEBIT", "1234.56"), lnP("lc", "income:salary:mobile", "CREDIT", "1234.56")] }),
  fx: mkEntry({ id: "je-fx", lines: [lnP("lu", "assets:usd", "DEBIT", "100", { currency: "USD", fx_rate: "1.35" }), lnP("lm", "income:fx", "CREDIT", "100", { currency: "USD" })] }),
  acc: mkEntry({ id: "e1", entry_date: "2023-01-01", memo: "Pay", source_type: "manual", lines: [lnP("l1", "a3", "DEBIT", "25", { journal_entry_id: "e1" })] }),
};

export const WB_FIX = {
  anomStat: { ...WB_STATS, total_transactions: 10, matched_transactions: 8, unmatched_transactions: 2, pending_review: 1, auto_accepted: 7, match_rate: 80, score_distribution: { "90-100": 5, "80-89": 0, "60-79": 2, "0-59": 0 } },
  anomPend: { items: [{ ...WB_MATCH, match_score: 88, transaction: { ...WB_MATCH.transaction, description: "Transfer" } }] },
  anomList: [{ anomaly_type: "spike", severity: "high", message: "Unusual amount" }],
  actions: [
    ["Run Matching", OP.WB_RUN, { body: {} }],
    ["Batch Accept ≥ 85", OP.S2_BATCH, { body: { action: "accept", match_ids: ["m1"] } }],
    ["Accept", OP.WB_MATCH, { path: { match_id: "m1" }, body: { action: "accept" } }],
    ["Reject", OP.WB_MATCH, { path: { match_id: "m1" }, body: { action: "reject" } }],
  ] as const,
  qErrs: [[OP.WB_STAT, "stats down", "Failed to load reconciliation stats: stats down"], [OP.WB_PEND, "pending down", "Failed to load pending matches: pending down"]] as const,
  mErrs: [["Run Matching", "run failed"], ["Batch Accept ≥ 85", "Batch accept failed: batch failed"], ["Accept", "Failed to accept match: accept failed"], ["Reject", "Failed to reject match: reject failed"]] as const,
  links: { items: [{ ...WB_MATCH, transaction: { ...WB_MATCH.transaction, statement_id: "stmt-42", statement_filename: "dbs-2026-01.pdf" } }, { ...WB_MATCH, id: "m2", transaction: { ...WB_MATCH.transaction, id: "t2", description: "Utilities" } }] },
  inv: [
    ["reconciliation.run", "Run Matching", OP.WB_RUN, { body: {} }],
    ["reconciliation.accept-match", "Accept", OP.WB_MATCH, { path: { match_id: "m1" }, body: { action: "accept" } }],
    ["reconciliation.reject-match", "Reject", OP.WB_MATCH, { path: { match_id: "m1" }, body: { action: "reject" } }],
    ["reconciliation.batch-accept", "Batch Accept ≥ 85", OP.S2_BATCH, { body: { action: "accept", match_ids: ["m1"] } }],
  ] as const,
  tabs: [
    ["tab=matches", /Matches/, "Reconciliation Workbench"],
    ["tab=unmatched&statement_id=s1", /Unmatched/, "Mock Unmatched Board"],
    ["tab=review-queue&check_type=duplicate&run_id=run-42", /Review queue/, "Mock Review Queue"],
  ] as const,
  defs: [
    ["", 1, /Unmatched/, "Mock Unmatched Board"],
    ["tab=unknown", 1, /Unmatched/, "Mock Unmatched Board"],
    ["", 0, /Matches/, "Reconciliation Workbench"],
    ["tab=unknown", 0, /Matches/, "Reconciliation Workbench"],
  ] as const,
  hrefs: ["/reconciliation?tab=matches", "/reconciliation?tab=unmatched", "/reconciliation?tab=review-queue"],
};

export const UP_FIX = {
  k: "statement_model_v1",
  g: "google/gemini-3-flash-preview",
  q: "qwen/qwen-2.5-vl-7b-instruct:free",
  badLS: { getItem: () => { throw new Error("r"); }, setItem: () => { throw new Error("w"); }, removeItem: vi.fn(), clear: vi.fn(), key: vi.fn(), length: 0 },
  badFiles: [
    [undefined, "bad.exe", "application/octet-stream", "x", "Invalid file type: .exe. Allowed: PDF, CSV, PNG, or JPG"],
    [undefined, "big.pdf", "application/pdf", 10 * 1024 * 1024 + 1, "File exceeds 10MB limit"],
    ["statement", "d.csv", "text/csv", "a", "Invalid file type: .csv. Allowed: PDF, PNG, or JPG"],
    ["csv", "s.pdf", "application/pdf", "x", "Invalid file type: .pdf. Allowed: CSV"],
  ] as const,
};

export const UNM_FIX = {
  je: { id: "je1", entry_date: "2026-01-11", memo: "Card payment", status: "posted", total_amount: "88.00" },
  incItem: { ...UNM_ITEM, id: "u2", description: "Salary", direction: "IN" as const },
  incAcc: { ...UNM_EXP, id: "income-1", name: "Income - Salary", type: "INCOME" as const },
  secAcc: { id: "expense-2", name: "Expense - Utilities", type: "EXPENSE", currency: "SGD", is_active: true },
};

export async function fillUnm(intent = "expense", accId?: string) {
  await fChg("Transaction type", intent);
  if (accId) await fChg("Counter account", accId);
  chg("Report category", "DINING");
  chg("Review rationale", "Receipt reviewed.");
}

export const S2_PARTS_FIX = {
  pm: mkMatch({ amount: "1200" }),
  lm: mkMatch({ id: "m2", match_score: 55, description: "Low confidence transfer", amount: null, txn_date: null }),
  dup: mkCheck(),
  custom: mkCheck({ id: "c2", check_type: "manual_review" as ConsistencyCheck["check_type"], details: { reason: "Needs human review" }, severity: "low" }),
  guards: [
    ["Resolve consistency checks first", mkQueue({ pending_matches: [mkMatch({ amount: "1200" })], consistency_checks: [mkCheck()], has_unresolved_checks: true }), undefined, [mkCheck()]],
    ["Clear Processing Account pending transfers first", mkQueue({ pending_matches: [mkMatch({ amount: "1200" })] }), { pending_count: 1, pending_total: "10", currency: "SGD", oldest_pending_date: "2026-01-01" }, []],
    ["No pending matches remain", mkQueue({ pending_matches: [] }), undefined, []],
  ] as const,
};

export const STMTS_FIX = {
  keys: [["portfolio-holdings", false, ""], ["portfolio-summary", ""], ["portfolio-allocation", "asset"], ["reports-net-worth-allocation", "", "SGD", true]] as const,
  brokFailMsg: "The positions could not be imported. Retry, or delete the file and upload it again.",
  moomooReason: "The positions source does not state an as-of date for 2 of 2 positions. The import needs the date that the source states.",
  statuses: [
    ["parsed", "ready.pdf", "Ready to review", "parsed", true],
    ["uploaded", "fresh.pdf", "Uploaded", "uploaded", false],
    ["rejected", "rejected.pdf", "Rejected", null, false],
    ["frobnicating" as BankStatement["status"], "weird.pdf", "frobnicating", null, false],
  ] as const,
};

export const DP_FIX = {
  parsed: mkStmt({ opening_balance: 1000, closing_balance: 1500, transactions: [mkTxn({ id: "t1", txn_date: "2026-01-02", description: "Salary", reference: "R1", amount: 500, direction: "IN", balance_after: 1500, status: "matched" })] }),
  brok: mkStmt({ original_filename: "moomoo-2026-01.pdf", institution: "Moomoo", currency: "USD", opening_balance: null, closing_balance: null }),
  invKeys: [["portfolio-holdings", false, ""], ["portfolio-summary", ""], ["reports-net-worth-allocation", "", "SGD", true], ["statements"]] as const,
  cc: mkStmt({ institution: "Liberty National Credit Card", original_filename: "bsb_002_liberty_national.pdf", currency: "USD", account_id: null, opening_balance: -1847.32, closing_balance: -9532.91, source_result_digest: "d".repeat(64), source_missing_facts: ["account_last4"], source_envelope_reviewable: true, reviewed_envelope: null, balance_validation_result: null }),
  ccAccts: [{ id: "a-1", name: "Checking", type: "ASSET", currency: "USD", is_active: true, is_system: false }, { id: "l-1", name: "Existing Card", type: "LIABILITY", currency: "USD", is_active: true, is_system: false }],
};

export const REV_FIX = {
  bal: REV_BAL,
  stmt: REV_STMT,
  conflicts: REV_CONFLICTS,
  dormant: { ...REV_STMT, account_id: "a1", confidence_score: 75, closing_balance: 100, transactions: [], source_result_digest: "a".repeat(64), source_missing_facts: [], source_envelope_reviewable: true, reviewed_envelope: null },
  missing: { ...REV_STMT, account_id: null, currency: null, period_start: null, opening_balance: null, closing_balance: null, source_result_digest: "a".repeat(64), source_missing_facts: ["statement_currency", "period", "balances"], source_envelope_reviewable: true, reviewed_envelope: null },
  confirmed: { ...REV_STMT, account_id: "a1", source_result_digest: "a".repeat(64), source_missing_facts: ["statement_currency", "period", "balances"], reviewed_envelope: { id: "review-1", source_result_digest: "a".repeat(64), account_id: "a1", currency: "SGD", period_start: "2024-01-01", period_end: "2024-01-31", opening_balance: "100.00", closing_balance: "120.00", rationale: "The CSV has no statement header.", review_trace_record_id: "trace-1", created_at: "2024-02-01T00:00:00Z" } },
  unsup: { ...REV_STMT, source_result_digest: "a".repeat(64), source_missing_facts: ["transaction_currency"], source_envelope_reviewable: false, reviewed_envelope: null },
  unrated: { id: "txn-unrated", txn_date: "2024-01-03", description: "PAYNOW TRANSFER", reference: "REF-1", amount: 20, direction: "OUT", currency: "SGD", balance_after: 120 },
  acct2826: { ...REV_STMT, account_id: null, source_envelope_reviewable: false, source_missing_facts: [], transactions: [{ id: "txn-2826", txn_date: "2024-01-03", description: "ACME SALARY", reference: "REF-2826", amount: 100, direction: "IN", currency: "SGD", balance_after: 200, suggested_category: "Salary", confidence_score: 0.95, suggestion_status: "accepted" }] },
  previewCases: [["statement.pdf", "statements/statement.pdf", true], ["october.csv", "statements/october.csv", false], ["OCTOBER.CSV", "statements/OCTOBER.CSV", false]] as const,
};

export const RUN_FIX = {
  activeMsg: "A run is already in progress for this statement. Wait for it to end, then run again.",
  changedMsg: "The statement changed. Reload the page.",
  invalidMsg: "The hints are not valid. Check the keywords and the note.",
  ctrlMsg: "Keywords and the note cannot contain control characters.",
  hbActive: [mkUserRun({ seq: 1, state: "failed", error_code: "heartbeat_lost", actor_kind: "system", trigger: "upload" }), mkUserRun({ seq: 2, state: "running", actor_kind: "system", trigger: "auto_retry", finished_at: null })],
  hbDone: [mkUserRun({ seq: 1, state: "failed", error_code: "heartbeat_lost", trigger: "upload" }), mkUserRun({ seq: 2, state: "failed", error_code: "heartbeat_lost" })],
  hbUploadFail: [mkUserRun({ seq: 1, state: "failed", error_code: "heartbeat_lost", trigger: "upload" }), mkUserRun({ seq: 2, state: "running", finished_at: null })],
  attempts: [mkUserRun({ seq: 1, actor_kind: "system", trigger: "upload", state: "failed", error_code: "extraction_error", error_message: "The parse failed." }), mkUserRun({ seq: 2, hints: { keywords: ["interest", "FX fee"], note: "Credits carry a CR suffix.\nYear is 2026." } })],
  badCtrl: ["\u0007", "\u0000", "\u200e\u0085"],
};

export function scriptStmtReads(api: ApiMock, ans: Array<() => Promise<unknown>>, fb: () => Promise<unknown> = () => Promise.resolve(null)) {
  const q = [...ans];
  mockStmtApi(api, { extra: (op) => (op === OP.STMT ? (q.shift() ?? fb)() : op === OP.RUNS ? Promise.resolve({ items: [], total: 0 }) : Promise.resolve(null)) });
}

export const DP_BADGES = [["approved", "badge-success"], ["rejected", "badge-error"], ["parsed", "badge-warning"], ["uploaded", "badge-muted"]] as const;
export const DP_IMPORT_ERR = "Statement must be in PARSED or APPROVED status: https://s3.example.com/private/token=abc123";
export const DP_CC_BODY = { name: "Liberty National Credit Card account", type: "LIABILITY", currency: "USD" };

export const stmtsMockState = { onUpload: null as (() => void) | null };
export const stmtsLinkMock = () => ({ default: ({ href, children, ...r }: { href: string; children: ReactNode }) => React.createElement("a", { href, ...r }, children) });
export const stmtsUploaderMock = () => ({
  default: ({ onUploadComplete, kind = "all" }: { onUploadComplete: () => void; kind?: string }) => {
    stmtsMockState.onUpload = onUploadComplete;
    return React.createElement("button", { onClick: onUploadComplete }, `UploadMock-${kind}`);
  },
});
export const stmtsConfirmMock = () => ({
  default: ({ isOpen, onConfirm, onCancel, title }: { isOpen: boolean; onConfirm: () => void; onCancel: () => void; title?: string }) =>
    React.createElement("div", { "data-testid": isOpen ? "confirm-dialog" : "confirm-dialog-closed" }, isOpen ? React.createElement("span", null, title) : null, React.createElement("button", { onClick: onConfirm }, isOpen ? "Confirm Delete" : "Confirm Delete (no selection)"), React.createElement("button", { onClick: onCancel }, "Cancel Delete")),
});

export const STMTS_DATA = {
  parsingNull: { period_start: null, period_end: null, currency: null, confidence_score: null, opening_balance: null, closing_balance: null, balance_validated: null },
  needsRev: { institution: "Unknown", period_start: null, period_end: null, opening_balance: null, closing_balance: null, balance_validated: false, validation_error: "Balance mismatch" },
  ibkr: { institution: "Interactive Brokers", confidence_score: 20, balance_validated: null, opening_balance: null, closing_balance: null, period_start: null, period_end: null, validation_error: "Economic review required: intent_missing", brokerage_import_failed: true, brokerage_import_failure_reason: "The positions could not be imported. Retry, or delete the file and upload it again." },
  moomoo: { institution: "Moomoo", validation_error: null, brokerage_import_failed: true, brokerage_import_failure_reason: "The positions source does not state an as-of date for 2 of 2 positions. The import needs the date that the source states.", balance_validated: null },
  covTexts: ["DBS Checking", "Up to date", "OCBC Savings", "1 issue", "Gap"],
};

export const REV_DATA = {
  dormantAccts: { items: [{ id: "a1", name: "Dormant Bank", type: "ASSET", currency: "SGD", is_active: true }], total: 1 },
  cashAccts: { items: [{ id: "a1", name: "DBS Cash", type: "ASSET", currency: "SGD", is_active: true }], total: 1 },
  existingAccts: { items: [{ id: "acc-existing", name: "DBS Multiplier", type: "ASSET", currency: "SGD", is_active: true }], total: 1 },
  twoAccts: { items: [{ id: "acc-ocbc", name: "OCBC Savings", type: "ASSET", currency: "SGD", is_active: true }, { id: "acc-dbs", name: "DBS Cash Account", type: "ASSET", currency: "SGD", is_active: true }], total: 2 },
  mismatchBal: { ...REV_BAL, opening_match: true, closing_match: false, closing_delta: "5.00", cross_period_match: false, cross_period_delta: "120.00" },
  gapBal: { ...REV_BAL, opening_match: true, closing_match: true, cross_period_match: false, cross_period_delta: "+3000.00", previous_period_end: "2024-01-31", has_date_gap: true },
  confirmFields: [["Custody account", "a1"], ["Statement currency", "SGD"], ["Period start", "2024-01-01"], ["Period end", "2024-01-31"], ["Opening balance", "100"], ["Closing balance", "120"], ["Why are these facts confirmed?", "The CSV has no statement header."]] as const,
  pend3: { items: [{ id: "s0" }, { id: "s1" }, { id: "s2" }], total: 3 },
  noEnvStmt: { ...REV_STMT, account_id: null, source_envelope_reviewable: true, source_missing_facts: [], source_result_digest: "digest-1", reviewed_envelope: null },
  unratedRev: { ...REV_STMT, account_id: null, source_envelope_reviewable: true, source_missing_facts: ["balances"], source_result_digest: "a".repeat(64), reviewed_envelope: null, transactions: [REV_FIX.unrated] },
  bankStmt: { ...REV_STMT, original_filename: "bsb_001_straits_capital.pdf", institution: "Straits Capital", file_path: "", status: "approved", transactions: [{ ...REV_STMT.transactions[0], status: "pending" }] },
};

export const S2_DATA = {
  scoreMatches: [mkMatch({ id: "h", match_score: 90 }), mkMatch({ id: "m", match_score: 70, amount: undefined, txn_date: undefined, description: undefined }), mkMatch({ id: "l", match_score: 30 })],
  filterCalls: [{ severity: [] }, { severity: ["high", "medium"] }, { checkType: "anomaly" }, { status: "resolved" }, { minScore: 45 }],
  run1Counts: { transfer: 1, duplicate: 1, anomaly: 1 },
  run2Counts: { transfer: 2, duplicate: 0, anomaly: 2 },
};

export const UNM_DATA = {
  compat: [["income", ["INCOME"]], ["loan_principal", ["LIABILITY"]], ["card_repayment", ["LIABILITY"]], ["unknown", []]] as const,
  disp: [["expense", UNM_EXP.id, "", "Reviewed.", false], ["unknown", UNM_EXP.id, "", "Reviewed.", false], ["investment_purchase", "asset-1", "", "Trade confirmed.", true]] as const,
  precise: { ...UNM_ITEM, id: "u-precise", amount: "12345678901234567890.12", currency: "USD" },
  postBody: { intent: "expense", counter_account_id: UNM_EXP.id, rationale: "Receipt reviewed.", category: "DINING" },
};

export const WB_DATA = {
  qSeq: [{ items: [WB_MATCH] }, { items: [{ ...WB_MATCH, transaction: { ...WB_MATCH.transaction, amount: 825 } }] }, { items: [] }],
};

export const UP_DATA = {
  noDef: "We couldn't find a default AI model. Refresh and try again.",
  netErr: "Unable to load AI models. Please try again.",
  invCat: "Please select or enter a category.",
};

export const TXN_DATA = {
  normInput: mkStmt({ status: "approved", transactions: [mkTxn({ id: "w1", description: "Salary", direction: "IN", confidence_tier: "HIGH", status: undefined }), mkTxn({ id: "w2", description: "PayNow", confidence_tier: "LOW", status: undefined })] }) as unknown as Schemas["BankStatementResponse"],
  multiTitles: ["Card fee", "PayNow", "Salary", "Grab", "Rent", "Groceries"],
  mobIds: ["f", "p", "s", "g", "r", "gr"],
  wireTitles: ["Oct 15 first low", "Oct 5 low", "Oct 25 top", "Oct 15 second"],
  unratedTitles: ["Fee", "Unrated", "Salary"],
};

export const AI_DATA = {
  tiers: ["DETERMINISTIC", "TRUSTED", "HIGH", "MEDIUM", "LOW"] as const,
  sugErr: "The corrected value is not a category. Use one of: SALARY",
  noChange: "Feedback saved. It did not change the suggestion.",
  rejNote: "Rejected. The approval uses the default category.",
  opts: ["DINING", "TRANSFER"],
  acts: ["Accept", "Reject", "Edit-then-Accept"],
  fbBody: { body: { suggestion_id: AI_FIX.id, action: "edit_accept", corrected_value: { value: "TRANSPORT" } } },
  auditTx: "00000000-0000-0000-0000-000000000013",
};

export const EV_DATA = {
  empty: { source_class: "esop_rsu_plan" as const, value: "", currency: "SGD", as_of_date: "", valuation_basis: "" as const, source_label: "", source_anchor: "", notes: "" },
  blockers: ["missing_value", "missing_as_of_date", "missing_valuation_basis", "missing_source_label"],
  p1: { component_type: "rsu", value: "12500", currency: "SGD", source: "Acme RSU grant (grant-2026.pdf p3)", valuation_basis: "employer_grant_document", notes: null },
  p2: { component_type: "other_liability", valuation_basis: "bank_statement", source: "Acme RSU grant", currency: "USD", notes: "Quarterly review" },
  classes: ["esop_rsu_plan", "property_statement", "liability_statement"],
};

export const LOW_DATA = {
  ok: 'Category updated to "Dining"',
  dbErr: "Database write error",
  emptyErr: "Please select or enter a category.",
  inTxn: { ...LOW_TXN, direction: "IN", proposed_category: "SALARY" },
  unratedTxn: { ...LOW_TXN, confidence_tier: null, confidence: undefined },
};

export const DETAIL_DATA = {
  statuses: ["draft", "posted", "reconciled", "void"] as const,
  baseTexts: [/Date/i, /Status/i, "posted", "manual entry", "No memo", /DR:/, /CR:/],
  mobChecks: ["assets:cash:mobile", "DEBIT", "SGD", "FX Rate", "SGD Base"],
};

export const LIN_DATA = {
  flat: ["ledger line", "extracted record", "atomic fact", "source document"],
  chain: ["source document", "atomic fact", "ledger line", "report line"],
  s0: ["Source: statement_upload", "Confidence: HIGH", "Version: v3"],
  blk: [{ code: "graph_node_missing", message: "No graph node for this anchor" }],
  blkTxt: ["No graph node for this anchor", "No source records are linked to this amount yet."],
};

export const S2_PAGE_DATA = {
  batchErr: "409 Conflict: unresolved consistency checks block batch approval",
  resBody: { path: { check_id: "c1" }, body: { action: "approve", note: "Looks good" } },
  chkQuery: { query: expect.objectContaining({ limit: 500 }) },
};

export const CK_EXTRA = {
  cfOv: { currency: "USD", summary: { net_cash_flow: "12.50" } },
  normExpect: [expect.objectContaining(CK.norm.is), expect.objectContaining({ ...CK.norm.cf, fx_warnings: [], summary: { ...CK.norm.cf.summary, beginning_cash: "0", ending_cash: "0" } })],
  calls: (api: ApiMock) => api.mock.calls.map(([op, q]) => [op, (q as { query: unknown }).query]),
};

export const CLS_ENV = { reviewed_envelope: null, source_envelope_reviewable: true, source_result_digest: "digest-1" };

export const AI_EXTRA = {
  fbSeq: [{ items: [AI_FIX.sug()], total: 1 }, { id: "f1", effect: "accepted" }, { id: "f2", effect: "rejected" }, { id: "f3", effect: "corrected" }, { id: "f4", effect: "recorded" }, new Error(AI_DATA.sugErr)],
  cardInfo: ["PAYNOW TRANSFER", "Expense - Food & Dining", "Merchant name indicates dining."],
  auditInfo: ["Audit Trail", "ai", "classified", /Food & Dining/],
  setPatch: { ...AI_FIX.setBase, enable_ai_classification: true, auto_accept_ai_suggestions_active: true },
  setErrGet: { ...AI_FIX.setBase, enable_ai_reconciliation: false, enable_ai_classification: true, auto_accept_ai_suggestions_active: true },
};

export const RUN_EXTRA = {
  hintKw: "interest, FX fee\n  salary ,\n\n",
  hintNote: "  Credits carry a CR suffix.\n  Second line.\n",
  hintReq: { path: { statement_id: "s1" }, body: { kind: "extract", hints: { keywords: ["interest", "FX fee", "salary"], note: "  Credits carry a CR suffix.\n  Second line.\n" } } },
  wsReq: { body: { kind: "extract", hints: { keywords: [], note: null } } },
  u2028Req: { body: { kind: "extract", hints: { keywords: ["FX fee", "rent due"], note: "first\nsecond\nthird" } } },
  clsReq: { path: { statement_id: "s1" }, body: { kind: "classify", hints: { keywords: ["rent", "salary"], note: "Credits are salary." } } },
  extReq: { body: { kind: "extract", hints: { keywords: ["interest"] } } },
  csvReq: { body: { kind: "classify", hints: { keywords: ["rent"] } } },
  rejReq: { body: { notes: "first\nsecond\nthird" } },
  s1Fail: [mkUserRun({ seq: 1, state: "failed", error_code: "extraction_error" })],
  reqRun: [mkUserRun({ seq: 1, state: "requested", started_at: null, finished_at: null })],
  clsRunning: [mkUserRun({ seq: 1, kind: "classify", state: "running", finished_at: null })],
};

export const REV_EXTRA = {
  prevUrl: "/reconciliation?tab=unmatched&statement_id=s1&return_to=%2Fstatements%2Fs1",
  aiUrl: "/audit?tab=needs-you&statement_id=s1&return_to=%2Fstatements%2Fs1#ai-suggestions",
  autoFillBtn: "Auto-Fill Default Categories & Approve",
  approvedMsg: "Statement approved. 2 journal entries created.",
  confMsg: /Statement details confirmed and linked to the current extraction result/i,
  unsupMsg: /transaction currency cannot be confirmed by a cash statement check/i,
  dormantMsg: /needs your confirmation before it can be used/i,
  reparseBody: { kind: "extract", hints: { keywords: [], note: null } },
};

export const STMTS_EXTRA = {
  intakes: ["No statements uploaded yet", "CSV import", "UploadMock-csv", "Manual records"],
  brokRow: (id = "s-ibkr") => mkStmt({ id, original_filename: "Interactive_Brokers_Positions_U1234567_20261031.csv", status: "parsed", ...STMTS_DATA.ibkr }),
  moomooRow: mkStmt({ id: "s-moomoo", original_filename: "moomoo-positions.csv", status: "parsed", opening_balance: 100, closing_balance: 200, ...STMTS_DATA.moomoo }),
  actionItems: [
    mkStmt({ id: "s-parsed", original_filename: "parsed.pdf", status: "parsed", opening_balance: 100, closing_balance: 200 }),
    mkStmt({ id: "s-approved", original_filename: "approved.pdf", status: "approved", institution: "OCBC", opening_balance: 100, closing_balance: 200 }),
    mkStmt({ id: "s-fallback", original_filename: "", status: "parsing", period_start: "2026-02-01", period_end: "2026-02-28", currency: "CNY", opening_balance: 100, closing_balance: 200 }),
  ],
};

export const navS1Mock = () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), useParams: () => ({ id: "s1" }), useSearchParams: () => new URLSearchParams() });
export const apiDlMock = () => Promise.resolve({ blob: new Blob(["%PDF"]), filename: "f.pdf" });
export const sheetOverlayMock = () => ({ Sheet: ({ isOpen, title, children }: { isOpen: boolean; title: string; children: ReactNode }) => (isOpen ? React.createElement("div", { role: "dialog", "aria-label": title }, children) : null) });
export const wbStubMocks = {
  unm: () => ({ default: () => React.createElement("div", null, "Mock Unmatched Board") }),
  s2: () => ({ Stage2ReviewQueue: ({ runId }: { runId?: string }) => React.createElement("div", { "data-testid": "mock-review-queue", "data-run-id": runId ?? "" }, "Mock Review Queue") }),
};

export const RUN_TBL = {
  normCases: [["", "   ", { body: { kind: "extract", hints: { keywords: [], note: null } } }], ["FX\u2028fee, rent\u2029due", "first\u2028second\u2029third", { body: { kind: "extract", hints: { keywords: ["FX fee", "rent due"], note: "first\nsecond\nthird" } } }]] as const,
  clsChoices: [
    ["parsed", "statement-jan.CSV", true, "rent", { body: { kind: "classify", hints: { keywords: ["rent"] } } }],
    ["rejected", "statement-jan.csv", false, "", { body: { kind: "extract" } }],
  ] as const,
  errMsg: { active: "The statement has an active run.", changed: "The statement changed.", unproc: "unprocessable" },
  invKeys: [["statement-runs", "s1"], ["statement-review"]],
  att2Kw: ["interest", "FX fee"],
  att1Has: ["System · Upload", "Failed", "Error: extraction_error", "No hints"],
  att2Has: ["Attempt 2", "User · Rerun", "Succeeded"],
};

export const DP_TBL = {
  hdrMeta: ["statement-jan.pdf", /DBS • SGD • 2026-01-01 to 2026-01-31/, /Confidence 92% \(/],
  wbSel: "statement-side-by-side-workbench",
  fnBadge: "statement-original-filename-badge",
  impBanner: "import-result-banner",
  impMsg: "Brokerage positions imported successfully",
  impErrBanner: "import-error-banner",
  impFail: ["Brokerage Import Failed", /\[URL\]/],
};

export const S2_TBL = {
  card: "stage2-mobile-match-card-m1",
  desk: "stage2-desktop-match-region",
  tblClass: ["table-fixed", "border-collapse"],
  res1: ["1 unresolved transfer"],
  res2: ["2 unresolved transfers", "0 duplicates", "2 anomalies"],
  sevColors: ["text-[var(--error)]", "text-[var(--warning)]", "text-muted"],
  typeLabels: ["Duplicate", "Transfer Pair", "Anomaly", "manual_review"],
  scoreCls: [["90", "text-[var(--success)]"], ["70", "text-[var(--warning)]"], ["30", "text-[var(--error)]"]] as const,
};

export const TXN_TBL = {
  badges: [["high", "badge-success"], ["medium", "badge-warning"], ["low", "badge-error"]] as const,
  noRoles: [/Approve Edits/, /Discard/],
  desk: "stage1-desktop-transaction-region",
  mobList: "stage1-mobile-transaction-list",
  lowCnt: "low-confidence-count",
  rowNum: "date-row-number",
};

export const REV_TBL = {
  confTitle: "Confirm missing source facts",
  confDlg: "Approve Statement",
  rejDlg: "Reject Statement",
  conflictsDlg: "Resolve Conflicts",
  conflictTypes: ["Duplicate Candidates", "Transfer Pair Candidates"],
  mismatchHas: ["Prior Gap (3198)", "Closing Mismatch", "Prior Δ: 120.00", "Closing Δ: 5.00"],
  gapHas: ["Prior Gap (3198)", /Unexplained Statement Gap Equity \(3198\)/i],
  econMsg: "Economic classification needs review before entries can be posted.",
  unratedMsg: "Transaction classifications need review",
  wb: "statement-side-by-side-workbench",
};

export const UP_TBL = {
  dzCls: "border-[var(--accent)]",
  csvMsg: "CSV files are parsed directly",
  selAi: "Please select an AI model",
  noFile: "Please select a file",
  dzPrompt: /drop files here/i,
  bankLbl: /bank \/ institution/i,
  aiLbl: /ai model/i,
  upOp: "upload_statement_statements_post",
};

export const EV_TBL = {
  miss: [["Valuation basis", "Valuation basis is required"], ["As-of date", "As-of date is required"]] as const,
  okRes: { errors: {}, blockers: [] },
};

export const S2_PAGE_TBL = {
  loadErr: "Failed to load review queue",
  blockMsg: "Unresolved consistency checks block batch approval",
  resReq: { path: { check_id: "c1" }, body: { action: "approve", note: "Looks good" } },
};

export const LOW_TBL = {
  states: [
    [{ isOpen: true, transaction: LOW_TXN }, ["Review Low-Confidence Transaction", "Starbucks Coffee #998", "-SGD 5.50", /2024-03-15/]],
    [{ isOpen: true, transaction: { ...LOW_TXN, direction: "IN", confidence_tier: undefined, confidence: "medium" } }, ["+SGD 5.50", "medium"]],
  ] as const,
  corrReq: { body: { transaction_id: "txn-123", corrected_category: "DINING" } },
};

export const LOW = {
  ...LOW_DATA, ...LOW_TBL, txn: LOW_TXN, prompt: "Starbucks Coffee #998",
  noLbls: [/Transaction Amount/i, /Transaction Direction/i] as const,
  save: /Save Correction/i, ask: /Ask AI Assistant/i, cls: "Close modal", cat: /Classification Category/i,
};

export const EV = {
  ...EV_FIX, ...EV_DATA, ...EV_TBL, base: BASE_EV_FORM, panel: "recent-evidence-panel", badge: "manual-trusted-badge",
  srcTxt: "Acme RSU grant (grant-2026.pdf p3)", saveErr: "Failed to save evidence: save failed", none: "No evidence recorded yet.",
  save: "Save evidence", sc: "Source class", val: "Value / amount", anc: "Source anchor (optional)", blk: "evidence-readiness-blocker", emp: /employer grant document/i,
};

export const CLS = {
  ...CLS_MSG, env: CLS_ENV, errMsg: "The statement has an active run.", errObj: { active_run_id: "run-2" },
  why: /Why are these facts confirmed/, cfBtn: "Confirm statement details", auto: /Auto-Fill Default Categories/,
  pa: "parsing-attempts", pa1: "parsing-attempt-1", pa2: "parsing-attempt-2",
};

export const AI = {
  ...AI_FIX, ...AI_DATA, ...AI_EXTRA, reconLbl: "Enable AI reconciliation", clsLbl: "Enable AI classification", saveBtn: /Save changes/i,
  mobList: "ai-suggestions-mobile-list", corrLbl: "Corrected value", editBtn: "Edit-then-Accept", sugErrMsg: "suggestions unavailable", setErrMsg: "settings unavailable",
};

export const TXN = {
  ...TXN_FIX, ...TXN_DATA, ...TXN_TBL, lowMsg1: "1 low confidence · shown first", lowMsg2: "2 low confidence · shown first",
  tbl4: { width: "calc(100% - 4px)" }, tbl16: { width: "calc(100% - 16px)" },
  mob1: "stage1-mobile-transaction-card-t1", row6: "Row 6 of 6",
  cls: ["overflow-y-auto", "overflow-x-hidden"] as const, tblCls: ["table-fixed", "border-collapse"] as const,
};

export const UP = {
  ...UP_FIX, ...UP_DATA, ...UP_TBL,
  warns: { r: `[Storage] Failed to read ${UP_FIX.k}:`, w: `[Storage] Failed to write ${UP_FIX.k}:`, rm: `[Storage] Failed to remove ${UP_FIX.k}:` },
  pdf: (n = "s.pdf") => mkFile(n, "application/pdf"),
  csv: (n = "statement.csv", c = "a,b") => mkFile(n, "text/csv", c),
  png: (n = "statement.png") => mkFile(n, "image/png"),
};

export const WB = {
  ...WB_FIX, ...WB_DATA, stats: WB_STATS, match: WB_MATCH, navLbl: "Reconciliation workspace views",
  anomTitle: "Anomaly Signals", hdr: ["Reconciliation Workbench", "Score 88"], emptyMsgs: ["No pending matches", "Select a match to review"],
  runM: "Run Matching", srcLnk: "View source statement", srcSt: "View source statement (dbs-2026-01.pdf)",
};

export const UNM = {
  ...UNM_FIX, ...UNM_DATA, item: UNM_ITEM, exp: UNM_EXP, retLnk: "Return to statement review",
  doneTxt: /All transactions for this statement are classified/i, incompErr: "counter account is incompatible",
  dupErr: "Account name already exists", unavailErr: "unmatched queue unavailable",
  xferMsg: /must be paired in the reconciliation workbench/i, unkMsg: /Unknown transaction type/i,
  postBtn: "Confirm and Post", createAcc: "Create Account", tt: "Transaction type", ca: "Counter account", rc: "Report category", rr: "Review rationale",
};

export const S2 = {
  ...S2_PARTS_FIX, ...S2_DATA, ...S2_TBL, dlg: "Resolve Consistency Check", approveRun: "Approve Run", approveSel: "Approve Selected",
  overlay: ".fixed.inset-0[aria-hidden='true']", sel1: "Select match m1", sal: "Salary transfer", rcFirst: "Resolve consistency checks first",
  noM: "No pending matches", q1: "check_type=duplicate&status=pending&severity=high,medium&min_score=60",
  u1: "/reconciliation?tab=review-queue&from=attention", u2: "/reconciliation?check_type=anomaly&status=resolved&severity=medium&min_score=60",
};

export const STMTS = {
  ...STMTS_FIX, ...STMTS_DATA, ...STMTS_EXTRA, wf: WF_DATA, delOk: "Statement deleted successfully",
  delTitle: "Delete Statement", noStmts: "No statements uploaded yet", parsingTitle: "AI Parsing in Progress",
  impOk: "Brokerage positions imported", upBtn: "UploadMock-statement", delBtn: "Confirm Delete", canBtn: "Cancel Delete",
  noSelBtn: "Confirm Delete (no selection)", ibkrRow: "upload-statement-row-s-ibkr", ready: "Ready to review",
  noLinks: 'a[href="/notifications"], a[href="/processing"], a[href$="/review"]',
};

export const DP = {
  ...DP_FIX, ...DP_TBL, badges: DP_BADGES, impErr: DP_IMPORT_ERR, ccBody: DP_CC_BODY,
  parsing: { ...DP_FIX.parsed, status: "parsing", parsing_progress: 50 },
  hdr70: /Confidence 70% \(\S+/, hdr92: /Confidence 92% \(/, impBtn: /import brokerage positions to portfolio/i,
  impShort: /import brokerage/i, portLnk: /view portfolio after import/i, resume: "Resume Auto-Refresh", stopped: "Auto-refresh Stopped",
  prog: /Parsing in progress/, fail: "Parsing Failed", del: "Delete statement", nf: "Statement not found", ra: "Run again",
};

export const REV = {
  ...REV_FIX, ...REV_DATA, ...REV_EXTRA, ...REV_TBL, backAtt: /Back to Needs Confirmation/i, attUrl: "/audit?tab=needs-you",
  custLbl: "Custody account", createAcc: "Create account", lowTitle: "Review Low-Confidence Transaction",
  cfd: "Confirm statement details", lStmt: "Loading statement", fStmt: "Failed to load statement", rejBy: "Rejected by reviewer",
  dbsMsg: 'Account "DBS account" created and selected.', prevCol: "stage1-desktop-transaction-region", pdfH: "PDF Preview",
  autoMsg: /filed under default categories/, pauseMsg: /Approve is paused/i, pausedAction: "confirm_distinct",
};

export const S2P = { ...S2_FIX, ...S2_PAGE_DATA, ...S2_PAGE_TBL, load: "Loading review queue...", appSel: /Approve Selected/i };

export const RUN = {
  ...RUN_FIX, ...RUN_EXTRA, ...RUN_TBL, panel: "run-again-panel", attemptsId: "parsing-attempts",
  stopped: "Auto-refresh Stopped", activeTxt: /A run is in progress/, tooManyKw: "Use at most 20 keywords.",
  kwLen: "Each keyword has at most 64 characters.", clsOk: "Classification started", parseOk: "Parsing started",
  t0: "2026-01-01T00:00:00Z", t530: "2026-01-01T00:05:30Z", t701: "2026-01-01T00:07:01Z",
  pa1: "parsing-attempt-1", pa2: "parsing-attempt-2", kwLst: "Keywords of attempt 2",
};

export const T = {
  ren, clk, fClk, chg, fChg, chgEl, see, has, noTxt, dis, en, wFor, tick, cnt, callsOf,
  dlg, noDlg, box, alrt, fAlrt, noAlrt, tid, fTid, txt, fTxt, allTxt, fAllTxt, lbl, fLbl, noLbl,
  btn, fBtn, noBtn, lnk, hasLnk, fHasLnk, stRole, role, fRole, noRole,
  eq, mObj, txtIs, valIs, wValIs, wDis, wEn, wNoTxt, wCnt, wGt, wCall, hasOp, wOp, hasC, cN,
  hasCls, noCls, hasAttr, esc, sub, selOpt, deferred, memStorage, mockMM, rejectFlow, approveStmt,
};

export function s2PmProps(ov: Record<string, unknown> = {}) {
  return { matches: [mkMatch()], selectedMatches: new Set(["m1"]), actionLoading: false, hasUnresolvedChecks: false, onToggleMatch: vi.fn(), onToggleAll: vi.fn(), onBatchReject: vi.fn(), onBatchApprove: vi.fn(), ...ov };
}

export function s2RunProps(ov: Record<string, unknown> = {}) {
  return { runId: "run-1", unresolvedCounts: S2.run1Counts, processingPendingCount: 0, pendingMatchesCount: 3, actionLoading: false, approval: { disabled: false, reason: "Approve" }, onApproveRun: vi.fn(), ...ov };
}

export function revPreset(api: ApiMock, mode: "dormant" | "unsup" | "unrated" | "bank" | "gap") {
  if (mode === "dormant") mockStmtApi(api, { stmt: REV.dormant, rev: REV.dormant, extra: (op) => (op === OP.ACCTS ? Promise.resolve(REV.dormantAccts) : undefined) });
  else if (mode === "unsup") mockStmtApi(api, { stmt: REV.unsup, rev: REV.unsup });
  else if (mode === "unrated") mockStmtApi(api, { stmt: REV.stmt, rev: REV.unratedRev, extra: (op) => (op === OP.ACCTS ? Promise.resolve(REV.twoAccts) : undefined) });
  else if (mode === "bank") mockStmtApi(api, { stmt: REV.bankStmt, rev: REV.bankStmt });
  else mockStmtApi(api, { stmt: REV.stmt, rev: { ...REV.stmt, balance_validation_result: REV.gapBal } });
}

export function runMount(api: ApiMock, opts: Parameters<typeof setupRunApi>[1], ui: React.ReactElement) {
  api.mockReset();
  setupRunApi(api, opts);
  return render(ui);
}

export const aiSetApi = (api: ApiMock, mode: "ok" | "fail") => {
  api.mockImplementation((async (op: string) => {
    if (op === OP.SET_GET) return mode === "ok" ? AI.setBase : AI.setErrGet;
    if (mode === "ok") return AI.setPatch;
    throw new Error("update failed");
  }) as never);
};

export const evCls2Fields = [["Source class", "liability_statement"], ["Currency", "usd"], ["Notes (optional)", "Quarterly review"]] as const;

export const wbErrApi = (api: ApiMock) =>
  mockWbApi(api, {
    [OP.WB_RUN]: () => Promise.reject(new Error("run failed")),
    [OP.S2_BATCH]: () => Promise.reject(new Error("batch failed")),
    [OP.WB_MATCH]: (r) => Promise.reject(new Error((r?.body as { action?: string })?.action === "accept" ? "accept failed" : "reject failed")),
  });

export const s2ErrApis = {
  batchOk: { queue: mkQueue({ pending_matches: [S2_PARTS_FIX.pm, S2_PARTS_FIX.lm] }), extra: (op: string, req?: ReqArg) => op === OP.S2_BATCH ? (mObj(req ?? {}, { body: { action: "accept", match_ids: ["m1", "m2"] } }), Promise.resolve({ success: true, approved_count: 2 })) : undefined },
  resErr: { queue: mkQueue({ consistency_checks: [S2_PARTS_FIX.custom], has_unresolved_checks: true }), checks: () => Promise.reject(new Error("filter failed")), extra: (op: string) => (op === OP.S2_RES ? Promise.reject(new Error("resolve failed")) : undefined) },
  batchErr: { queue: mkQueue({ pending_matches: [S2_PARTS_FIX.pm] }), extra: (op: string, req?: ReqArg) => (op === OP.S2_BATCH ? Promise.reject(new Error((req?.body as { action?: string })?.action === "reject" ? "batch reject failed" : "approve run failed")) : undefined) },
  sumErr: { queue: mkQueue({ pending_matches: [S2_PARTS_FIX.pm], consistency_checks: [S2_PARTS_FIX.dup, S2_PARTS_FIX.custom] }), summary: () => Promise.reject(new Error("sum err")), checks: [S2_PARTS_FIX.dup, S2_PARTS_FIX.custom] },
};

export const len = (a: unknown, n: number) => expect(a).toHaveLength(n);
export const gt = (a: number, n: number) => expect(a).toBeGreaterThan(n);
export const gte = (a: number, n: number) => expect(a).toBeGreaterThanOrEqual(n);
export const inDoc = (el: unknown) => expect(el).toBeInTheDocument();
export const isNull = (el: unknown) => expect(el).toBeNull();
export const chk = (el: unknown, b = true) => (b ? expect(el).toBeChecked() : expect(el).not.toBeChecked());
export function renQC(ui: React.ReactElement, keys?: readonly (readonly unknown[])[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (keys) seedInv(client, keys);
  return { client, ...render(React.createElement(QueryClientProvider, { client }, ui)) };
}
export function renProbe(flow: string, ui: React.ReactElement, ids?: string[]) {
  const probe = createInvalidationProbe(flow as never, ids);
  return { probe, ...render(React.createElement(probe.wrapper, null, ui)) };
}

export const unmSeq = {
  s1: [{ items: [UNM.item], total: 1 }, { items: [{ ...UNM.exp, id: "other", currency: "USD" }], total: 1 }, UNM.exp, { id: "je1" }, { items: [], total: 0 }, { items: [UNM.exp], total: 1 }],
  err: [{ items: [UNM.item], total: 1 }, { items: [], total: 0 }, new Error("Account name already exists")],
  usd: [{ items: [UNM.item], total: 1 }, { items: [], total: 0 }, { ...UNM.exp, currency: "USD" }],
  multi: [{ items: [UNM.item, UNM.incItem], total: 2 }, { items: [UNM.exp, UNM.incAcc], total: 2 }, UNM.je, { items: [], total: 0 }, { items: [UNM.exp], total: 1 }],
  scoped: [{ items: [UNM.item], total: 1 }, { items: [UNM.exp], total: 1 }, UNM.je],
  precise: [{ items: [UNM.precise], total: 1 }, { items: [], total: 0 }],
};

export async function unmFill(intent = "expense", accId?: string) {
  await fChg("Transaction type", intent);
  if (accId) await fChg("Counter account", accId);
  chg("Report category", "DINING");
  chg("Review rationale", "Receipt reviewed.");
}

export function unmDlg(b = "Create counter account", name = "Dining", cur?: string) {
  clk(b);
  const d = role("dialog", "New Account");
  chgEl(within(d).getByPlaceholderText("e.g., Cash on Hand"), name);
  if (cur) chg("Currency *", cur, d);
  return d;
}

export function revMocks(api: ApiMock) {
  return {
    retry: () => {
      let n = 0;
      mockStmtApi(api, { extra: (op) => (op === OP.STMT || op === OP.REV ? (++n === 1 ? Promise.reject(new Error("network fail")) : Promise.resolve(REV.stmt)) : undefined) });
      return () => n;
    },
    mismatch: (retry: (...a: unknown[]) => void) =>
      mockStmtApi(api, { stmt: REV.stmt, rev: { ...REV.stmt, balance_validation_result: REV.mismatchBal }, extra: (op, req) => (op === OP.RUN_POST ? (retry(req?.body), Promise.resolve({})) : undefined) }),
    envelope: () => {
      let ok = false, done!: () => void;
      const posted = new Promise<void>((r) => { done = r; });
      mockStmtApi(api, { stmt: REV.stmt, rev: () => (ok ? REV.confirmed : REV.missing), extra: (op) => (op === OP.ACCTS ? Promise.resolve(REV.cashAccts) : op === OP.CONFIRM ? ((ok = true), done(), Promise.resolve({ id: "review-1" })) : undefined) });
      return posted;
    },
    inlineAcc: () => {
      let created = false; const acc = { id: "acc-1", name: "DBS account", currency: "SGD" };
      mockStmtApi(api, { stmt: REV.stmt, rev: REV.noEnvStmt, extra: (op) => (op === OP.ACCTS ? Promise.resolve({ items: created ? [acc] : [] }) : op === OP.ACCT_POST ? ((created = true), Promise.resolve(acc)) : undefined) });
    },
    cust2826: () => {
      let body: unknown = null;
      mockStmtApi(api, { stmt: REV.stmt, rev: REV.acct2826, extra: (op, req) => (op === OP.ACCTS ? Promise.resolve(REV.existingAccts) : op === OP.APPROVE ? ((body = req?.body), Promise.resolve({ journal_entries_created: 1 })) : undefined) });
      return () => body;
    },
    nav: () => {
      let status = "parsed";
      const mk = () => ({ ...REV.stmt, status, validation_error: status === "rejected" ? "Rejected by reviewer" : null });
      const ex = (op: string, req?: ReqArg) => op === OP.APPROVE ? ((status = "approved"), Promise.resolve({ journal_entries_created: 2 })) : op === OP.REJECT ? (expect(req?.body).toEqual({ notes: "Needs re-parse" }), (status = "rejected"), Promise.resolve({ success: true })) : undefined;
      return { reset: () => { status = "parsed"; mockStmtApi(api, { stmt: mk, rev: mk, pend: REV.pend3, extra: ex }); } };
    },
    econ409: (ApiErr: new (m: string, s: number) => Error) => {
      let econ = false, body: unknown = null;
      mockStmtApi(api, { stmt: REV.stmt, rev: () => ({ ...REV.stmt, validation_error: econ ? "Economic review required: intent_missing" : null }), extra: (op, req) => op === OP.APPROVE ? (econ ? ((body = req?.body), Promise.resolve({ journal_entries_created: 2 })) : ((econ = true), Promise.reject(new ApiErr("Economic review required: intent_missing", 409)))) : undefined });
      return () => body;
    },
    unratedApprove: () => {
      let body: unknown = null;
      mockStmtApi(api, { stmt: REV.stmt, rev: { ...REV.stmt, validation_error: null, transactions: [REV.unrated] }, extra: (op, req) => (op === OP.APPROVE ? ((body = req?.body), Promise.resolve({ journal_entries_created: 1 })) : undefined) });
      return () => body;
    },
    conflicts: () => mockStmtApi(api, { stmt: REV.stmt, conflicts: REV.conflicts, extra: (op, req) => (op === OP.RESOLVE_CONF ? (expect(req?.body).toEqual({ action: "confirm_distinct" }), Promise.resolve({ resolved: true, resolved_at: "2026-06-14T00:00:00Z" })) : undefined) }),
    lowModal: () => {
      let cat: string | null = null;
      mockStmtApi(api, { stmt: REV.stmt, rev: () => ({ ...REV.stmt, transactions: [{ ...REV.stmt.transactions[0], proposed_category: cat, confidence_tier: cat ? "HIGH" : "LOW" }] }), extra: (op, req) => (op === OP.CORR ? ((cat = (req?.body as { corrected_category: string }).corrected_category), Promise.resolve({ id: "corr-1", transaction_id: "txn-1", corrected_category: cat })) : undefined) });
    },
  };
}

export const stmtsBrokApi = (api: ApiMock) => {
  const brok = STMTS.brokRow();
  mockStmtsPageApi(api, { statements: [{ items: [brok] }, { items: [{ ...brok, brokerage_import_failed: false, brokerage_import_failure_reason: null }] }], extra: (op) => (op === OP.IMPORT ? Promise.resolve({ broker: "Interactive Brokers", parsed_positions: 2 }) : undefined) });
};

export const stmtsPollApi = (api: ApiMock, stmt: (id: string, name: string, status: BankStatement["status"]) => BankStatement) => {
  const parsing = { items: [stmt("s-poll", "parsing.pdf", "parsing")] }, ready = { items: [stmt("s-poll", "ready.pdf", "parsed")] };
  const poll = deferred<typeof parsing>(), td = deferred<typeof ready>(); let reads = 0;
  mockStmtsPageApi(api, { extra: (op) => op !== OP.STMTS ? undefined : ++reads === 1 ? Promise.resolve(parsing) : reads === 2 ? poll.promise : reads === 3 ? Promise.resolve(ready) : td.promise });
  return { parsing, ready, poll, td, reads: () => reads };
};

export const dpCcApi = (api: ApiMock, empty: boolean) =>
  mockStmtApi(api, { stmt: DP.cc, rev: DP.cc, extra: (op) => (op === OP.ACCTS ? Promise.resolve({ items: empty ? [] : DP.ccAccts, total: empty ? 0 : 2 }) : empty && op === OP.ACCT_POST ? Promise.resolve({ id: "l-new", name: "Liberty Card", type: "LIABILITY", currency: "USD" }) : undefined) });

export function dpMocks(api: ApiMock) {
  const { parsed, brok } = DP, parsing = DP.parsing;
  return {
    pollAbort: () => { const poll = deferred<typeof parsed>(); scriptStmtReads(api, [() => Promise.resolve(parsing)], () => poll.promise); return poll; },
    supersede: () => { const oldReq = deferred<typeof parsed>(); api.mockImplementationOnce(() => oldReq.promise as never).mockResolvedValueOnce({ ...parsed, id: "s2", original_filename: "new-statement.pdf" } as never); return oldReq; },
    stale: () => { const stale = deferred<typeof parsed>(); scriptStmtReads(api, [() => Promise.resolve(parsing), () => Promise.reject(new Error("p1")), () => Promise.reject(new Error("p2")), () => Promise.reject(new Error("p3")), () => stale.promise, () => Promise.resolve({ ...parsing, parsing_progress: 10 })]); return stale; },
    wbRun: (status: string, validation_error?: string) => {
      let cur = { ...parsed, status, ...(validation_error ? { validation_error } : {}) }; const retried = vi.fn();
      mockStmtApi(api, { stmt: () => cur, extra: (op) => (op === OP.RUN_POST ? (retried(), (cur = { ...parsed }), Promise.resolve({})) : undefined) });
      return retried;
    },
    imp: (ok: boolean) => mockStmtApi(api, { stmt: brok, extra: (op) => (op === OP.IMPORT ? (ok ? Promise.resolve(mkBrokRes()) : Promise.reject(new Error(DP.impErr))) : undefined) }),
    del: (ok: boolean) => mockStmtApi(api, { stmt: brok, extra: (op) => (op === OP.DEL_STMT ? (ok ? Promise.resolve(null) : Promise.reject(new Error("Failed to delete"))) : undefined) }),
    retryErr: () => mockStmtApi(api, { stmt: { ...brok, status: "rejected", validation_error: "Bad parse" }, extra: (op) => (op === OP.RUN_POST ? Promise.reject(new Error("retry failed")) : undefined) }),
    pollErr: () => api.mockResolvedValueOnce(parsing as never).mockRejectedValue(new Error("Poll Failure")),
    stuck: () => mockStmtApi(api, { stmt: { ...brok, status: "parsing", parsing_progress: 30 } }),
  };
}

export const stmtsPresets = (api: ApiMock, stmt: (id: string, name: string, status: BankStatement["status"], ex?: Record<string, unknown>) => BankStatement) => ({
  retry: () => mockStmtsPageApi(api, { statements: [new Error("load failed"), { items: [] }, { items: [stmt("s1", "stmt.pdf", "approved")] }] }),
  parsingNull: () => mockStmtsPageApi(api, { statements: [{ items: [stmt("s2", "parsing.pdf", "parsing", STMTS.parsingNull)] }] }),
  delOk: () => mockStmtsPageApi(api, { statements: [{ items: [stmt("s3", "delete.pdf", "approved")] }, { items: [] }], deletes: [undefined] }),
  delFail: () => mockStmtsPageApi(api, { statements: [{ items: [stmt("s4", "needs-review.pdf", "parsed", STMTS.needsRev)] }], deletes: [new Error("delete failed")] }),
  empty: () => mockStmtsPageApi(api, { statements: [{ items: [] }] }),
  moomoo: () => mockStmtsPageApi(api, { statements: [{ items: [STMTS.moomooRow] }] }),
  wf: () => mockStmtsPageApi(api, { statements: [{ items: STMTS.actionItems }], ...STMTS.wf }),
});
export const stmtsActionBtns = ["View Report", "View Report →", "View Transactions", "Review & Approve →"] as const;
export const stmtsActionRoutes = ["/reports?tab=balance-sheet", "/statements/s-approved", "/statements/s-parsed"] as const;

export const wbPresets = {
  anom: { [OP.WB_STAT]: () => Promise.resolve(WB.anomStat), [OP.WB_PEND]: () => Promise.resolve(WB.anomPend), [OP.WB_ANOM]: () => Promise.resolve(WB.anomList) },
  links: { [OP.WB_PEND]: () => Promise.resolve(WB.links) },
  seq: () => { const q = [...WB.qSeq]; return { [OP.WB_PEND]: () => Promise.resolve(q.shift() ?? { items: [] }) }; },
  waitStat: () => { let res!: (v: unknown) => void; return { ov: { [OP.WB_STAT]: () => new Promise((r) => { res = r; }), [OP.WB_PEND]: () => Promise.resolve({ items: [] }) }, resolve: (v: unknown) => res(v) }; },
};

export const runErrCases = (ApiErr: new (m: string, s: number, k: string, r?: null, d?: never) => Error) => [
  ["409 active run", () => new ApiErr(RUN.errMsg.active, 409, "conflict", null, { active_run_id: "run-active" } as never), RUN.activeMsg],
  ["409 changed", () => new ApiErr(RUN.errMsg.changed, 409, "conflict", null, { error_id: "conflict" } as never), RUN.changedMsg],
  ["422 hints", () => new ApiErr(JSON.stringify({ detail: [{ input: ["SECRET-KEYWORD"] }] }), 422, "validation_error"), RUN.invalidMsg],
] as const;

export const runHbOpts = (fin: () => boolean, up = false) => ({ status: () => (fin() ? "rejected" : "parsing"), runs: () => (fin() ? RUN.hbDone : up ? RUN.hbUploadFail : RUN.hbActive) });
export const runPollOpts = (st: () => StatementRun["state"]) => ({ runs: () => [mkUserRun({ seq: 1, state: st(), finished_at: st() === "running" ? null : "2026-01-05T08:01:00Z" })] });
export const kws = (n: number, l = 5) => Array.from({ length: n }, (_, i) => `${i}`.padEnd(l, "k")).join(", ");

export const s2Parts = {
  pmEmpty: { matches: [], selectedMatches: new Set<string>() },
  pmScores: { matches: S2.scoreMatches, selectedMatches: new Set(["h", "m", "l"]), hasUnresolvedChecks: true },
  run2: { unresolvedCounts: S2.run2Counts, processingPendingCount: 4, pendingMatchesCount: 0, actionLoading: true, approval: { disabled: true, reason: "Resolve consistency checks first" } },
};

export const revBlockModes = [
  ["dormant", "Confirm source facts", REV.dormantMsg, "a1", false],
  ["unsup", "Source review required", REV.unsupMsg, "", true],
] as const;

export const clsErrRuns = (a: string) => [mkRun({ seq: 1 }), a === "confirm" ? mkRun({ seq: 2, state: "running", finished_at: null }) : mkClassifyRun("running")];
export function evFill(v = "12500", s = "Acme RSU grant") { chg("Value / amount", v); chg("Source label", s); }
export const cls409Opts = (a: string, runs: () => StatementRun[], ApiErr: new (m: string, s: number, k: string, r?: null, d?: never) => Error) =>
  [runs, a === "confirm" ? CLS.env : {}, () => Promise.reject(new ApiErr(CLS.errMsg, 409, "conflict", null, CLS.errObj as never))] as const;
export const checkCallsNoSecret = (calls: unknown[][], secret: string) => { for (const c of calls) expect(JSON.stringify(c[1] ?? {})).not.toContain(secret); };
export const sigOf = (api: ApiMock, op: string, i: number) => callsOf(api, op)[i]?.[1]?.signal;
export const aborted = (s?: AbortSignal) => expect(s?.aborted).toBe(true);
export const checkInvKeys = (inv: { mock: { calls: unknown[][] } }, keys: readonly (readonly unknown[])[]) => {
  const ks = inv.mock.calls.map((c) => JSON.stringify((c[0] as { queryKey?: unknown } | undefined)?.queryKey));
  for (const k of [...keys, ...LEDGER_DERIVED_QUERY_KEYS]) expect(ks).toContain(JSON.stringify(k));
};
export const listIds = (root: HTMLElement, prefix: string) =>
  within(root).getAllByRole("listitem").map((i) => i.dataset.testid).filter((d) => d?.startsWith(prefix));
export const listTxts = (root: HTMLElement, name: string) =>
  within(within(root).getByRole("list", { name })).getAllByRole("listitem").map((c) => c.textContent);
export const runRej422 = (ApiErr: new (m: string, s: number, k: string) => Error) =>
  ({ status: "parsed", runs: () => [], reject: () => Promise.reject(new ApiErr(JSON.stringify({ detail: [{ input: "SECRET-REJECT-NOTE" }] }), 422, "validation_error")) });
export const runCls409 = (ApiErr: new (m: string, s: number, k: string, r?: null, d?: never) => Error, reply: () => () => Promise<unknown>) =>
  ({ status: "parsed", runs: () => [mkUserRun({ seq: 1 })], post: () => reply()() });
export const err409 = (ApiErr: new (m: string, s: number, k: string, r?: null, d?: never) => Error, msg: string, d: Record<string, unknown>) =>
  () => Promise.reject(new ApiErr(msg, 409, "conflict", null, d as never));
export const err422 = (ApiErr: new (m: string, s: number, k: string, r?: null, d?: never) => Error, msg: string, d: Record<string, unknown>) =>
  () => Promise.reject(new ApiErr(msg, 422, "validation_error", null, d as never));
export const unmBadLs = () => ({ getItem: () => "not-json", setItem: () => { throw new Error("quota"); }, removeItem: vi.fn() });
export const revTitleOk = (fn1: (s: Record<string, unknown>) => string, fn2: (s: { institution?: string; original_filename?: string; brokerage_import_failed?: boolean }) => boolean) => {
  expect(fn1({ original_filename: "", institution: "DBS", period_start: "2026-01-01", period_end: "2026-01-31" })).toBe("DBS (2026-01-01 – 2026-01-31)");
  expect([fn2({ institution: "Straits Capital", original_filename: "bsb_001_straits_capital.pdf", brokerage_import_failed: false }), fn2({ institution: "Interactive Brokers", original_filename: "ibkr.pdf", brokerage_import_failed: false })]).toEqual([false, true]);
};

export async function runVerifyAttempts(api: ApiMock, ui: React.ReactElement) {
  runMount(api, { runs: () => RUN.attempts }, ui);
  eq(listIds(await fTid(RUN.attemptsId), "parsing-attempt-"), [RUN.pa2, RUN.pa1]);
  const s2 = tid(RUN.pa2);
  has(RUN.att2Has, s2);
  eq(listTxts(s2, RUN.kwLst), RUN.att2Kw);
  txtIs(within(s2).getByText(/Note: Credits carry a CR suffix\./), "Year is 2026.");
  has(RUN.att1Has, tid(RUN.pa1));
}

export async function runHintChecks(api: ApiMock, ui: React.ReactElement, kw: () => HTMLElement, note: () => HTMLElement, post: (k: string, n: string) => void) {
  const inv = vi.spyOn(QueryClient.prototype, "invalidateQueries");
  try {
    const v = runMount(api, { runs: () => RUN.s1Fail }, ui);
    await fTid(RUN.panel); await wGt(api, OP.REV, 0);
    const b = [OP.STMT, OP.REV, OP.RUNS].map((op) => cnt(api, op));
    inv.mockClear(); post(RUN.hintKw, RUN.hintNote);
    await wCnt(api, OP.RUN_POST, 1); eq(callsOf(api, OP.RUN_POST)[0][1], RUN.hintReq);
    await wValIs(kw, ""); valIs(note(), "");
    for (const [i, op] of [OP.STMT, OP.REV, OP.RUNS].entries()) await wGt(api, op, b[i]);
    checkInvKeys(inv, RUN.invKeys); v.unmount();
  } finally { inv.mockRestore(); }
  runMount(api, { runs: () => [] }, ui);
  await fTid(RUN.panel);
  for (const [i, [k, n, req]] of RUN.normCases.entries()) {
    post(k, n); await wCnt(api, OP.RUN_POST, i + 1); mObj(callsOf(api, OP.RUN_POST)[i][1], req);
  }
}

export async function runPollCases(api: ApiMock, ui: React.ReactElement) {
  const v0 = runMount(api, { runs: () => RUN.reqRun }, ui);
  await see(RUN.activeTxt); dis("Run again"); v0.unmount();
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const setT = (t: string) => vi.setSystemTime(new Date(t));
  setT(RUN.t0); let fin = false;
  const v1 = runMount(api, runHbOpts(() => fin), ui);
  inDoc(within(await fTid(RUN.attemptsId)).getByText("Error: heartbeat_lost"));
  inDoc(within(tid(RUN.pa2)).getByText("Running")); eq(cnt(api, OP.RUN_POST), 0);
  setT(RUN.t530); await tick(3100); noTxt(RUN.stopped);
  setT(RUN.t701); await tick(3100); await see(RUN.stopped); dis("Run again"); v1.unmount();
  let st: StatementRun["state"] = "running";
  const v2 = runMount(api, runPollOpts(() => st), ui);
  await see(RUN.activeTxt); const ca = cnt(api, OP.RUNS);
  st = "succeeded"; await tick(3100); await wEn("Run again"); gt(cnt(api, OP.RUNS), ca);
  const ce = cnt(api, OP.RUNS); await tick(9000); eq(cnt(api, OP.RUNS), ce); v2.unmount();
  fin = false; runMount(api, runHbOpts(() => fin, true), ui);
  await see(/Parsing in progress/); fin = true; await tick(3100);
  await see("Parsing Failed"); await wEn("Run again"); clk("Run again"); await wCnt(api, OP.RUN_POST, 1);
}

export async function runCtrlChecks(api: ApiMock, ui: React.ReactElement, kw: () => HTMLElement, note: () => HTMLElement) {
  runMount(api, { runs: () => [] }, ui); await fTid(RUN.panel);
  hasAttr(note(), "maxlength", "500");
  chgEl(kw(), kws(20, 64)); en("Run again");
  chgEl(kw(), kws(21)); dis("Run again"); txtIs(alrt(), RUN.tooManyKw);
  chgEl(kw(), kws(1, 65)); txtIs(alrt(), RUN.kwLen);
  for (const b of RUN.badCtrl) { chgEl(kw(), `interest, bad${b}word`); dis("Run again"); txtIs(alrt(), RUN.ctrlMsg); }
  chgEl(kw(), "می\u200cخواهم");
  for (const b of ["\u0007", "\r"]) { chgEl(note(), `first${b}second`); dis("Run again"); }
  chgEl(note(), "a\u200db\n\twith tab"); en("Run again"); noAlrt();
}

export async function runRejectChecks(api: ApiMock, ui: React.ReactElement, cdlg: React.ReactElement, toast: ReturnType<typeof vi.fn>, ApiErr: new (m: string, s: number, k: string) => Error) {
  const v1 = runMount(api, runRej422(ApiErr), ui);
  await fClk("Reject"); const d1 = await dlg("Reject Statement"), b1 = box(d1);
  hasAttr(b1, "maxlength", "500"); chgEl(b1, "bad\u0007note"); clk("Reject", d1);
  await wCall(toast, RUN.ctrlMsg, "error"); eq(cnt(api, OP.REJECT), 0);
  chgEl(b1, "SECRET-REJECT-NOTE"); clk("Reject", d1);
  await wCall(toast, RUN.invalidMsg, "error");
  expect(JSON.stringify(toast.mock.calls)).not.toContain("SECRET-REJECT-NOTE"); v1.unmount();
  const v2 = runMount(api, { status: "parsed", runs: () => [] }, ui);
  await rejectFlow("first\u2028second\u2029third");
  await wFor(() => mObj(callsOf(api, OP.REJECT)[0][1], RUN.rejReq)); v2.unmount();
  const cEl = React.cloneElement(cdlg, { input: { label: "Reason", maxLength: 12 } });
  const { rerender, unmount } = ren(cEl); hasAttr(box(), "maxlength", "12");
  rerender(React.cloneElement(cdlg, { input: { label: "Reason" } }));
  expect(box()).not.toHaveAttribute("maxlength"); unmount();
  runMount(api, { status: "approved", runs: () => [mkUserRun({ seq: 1 })] }, ui);
  await fTid(RUN.attemptsId); isNull(screen.queryByTestId(RUN.panel)); noBtn("Retry Parse");
}

export async function dpPollingChecks(api: ApiMock, P: () => React.ReactElement, toast: ReturnType<typeof vi.fn>, setId: (id: string) => void) {
  const dm = dpMocks(api), reads = () => callsOf(api, OP.STMT);
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const poll = dm.pollAbort(), v1 = ren(React.createElement(P));
  await see(DP.prog); await tick(3000); len(reads(), 2);
  const sig1 = sigOf(api, OP.STMT, 1); expect(sig1).toBeInstanceOf(AbortSignal);
  await tick(6000); len(reads(), 2); v1.unmount(); aborted(sig1);
  poll.resolve(DP.parsed); await poll.promise; await tick(6000); len(reads(), 2); expect(toast).not.toHaveBeenCalled();

  vi.useRealTimers(); api.mockReset();
  const old = dm.supersede(), v2 = ren(React.createElement(P));
  await wFor(() => cN(api, 1)); const oldSig = api.mock.calls[0]?.[1]?.signal;
  setId("s2"); v2.rerender(React.createElement(P));
  await see("new-statement.pdf"); aborted(oldSig);
  old.resolve(DP.parsed); await old.promise; noTxt("statement-jan.pdf"); v2.unmount();

  vi.useFakeTimers({ shouldAdvanceTime: true }); api.mockReset(); setId("s1");
  dm.stale(); ren(React.createElement(P)); await see(DP.prog); await tick(9000); await see(DP.stopped);
  await act(async () => { btn(DP.resume).click(); btn(DP.ra).click(); await Promise.resolve(); });
  await wFor(() => len(reads(), 6)); aborted(sigOf(api, OP.STMT, 4)); await see(DP.prog);
}

export async function dpWbChecks(api: ApiMock, ui: React.ReactElement) {
  const dm = dpMocks(api); dm.wbRun("parsed");
  const v1 = ren(ui), wb = await fTid(DP.wbSel);
  for (const h of ["PDF Preview", "Transactions"]) inDoc(within(wb).getByRole("heading", { name: h }));
  txtIs(tid(DP.fnBadge), "Source file: statement-jan.pdf"); hasLnk("← Back to Upload", "/upload");
  isNull(document.querySelector('a[href$="/review"]')); expect(await fBtn("Approve")).toBeEnabled(); en("Reject"); v1.unmount();
  dm.wbRun("approved"); const v2 = ren(ui);
  await wFor(() => expect(api).toHaveBeenCalledWith(OP.REV, expect.anything()));
  noBtn("Approve"); noBtn("Reject"); v2.unmount();
  const retried = dm.wbRun("rejected", "parse failed"); ren(ui);
  await see(DP.fail); clk(DP.ra);
  await wCall(api, OP.RUN_POST, { path: { statement_id: "s1" }, body: REV.reparseBody });
  cN(retried, 1); await wNoTxt(DP.fail);
}

export async function dpLifecycleChecks(api: ApiMock, ui: React.ReactElement, toast: ReturnType<typeof vi.fn>) {
  const dm = dpMocks(api);
  vi.useFakeTimers({ shouldAdvanceTime: true }); vi.setSystemTime(new Date(RUN.t0));
  dm.stuck(); const v1 = ren(ui); await see(DP.prog);
  vi.setSystemTime(new Date(RUN.t701)); await tick(3000); await see(DP.stopped); clk(DP.resume);
  await wOp(api, OP.STMT, { signal: expect.any(AbortSignal) }); v1.unmount(); vi.useRealTimers();
  dm.retryErr(); const v2 = ren(ui); await see(DP.fail); clk(DP.ra);
  await wFor(() => gt(allTxt("retry failed").length, 0)); v2.unmount();
  dm.del(true); const v3 = ren(ui), d = await fBtn(DP.del);
  fireEvent.click(d); clk("Cancel"); fireEvent.click(d); await fClk("Delete");
  await wCall(api, OP.DEL_STMT, { path: { statement_id: "s1" } }); v3.unmount();
  dm.del(false); ren(ui); await fClk(DP.del); await fClk("Delete");
  await wCall(toast, "Failed to delete", "error");
}

export function s2CheckParts(C: {
  PendingMatchesPanel: React.ComponentType<never>;
  ConsistencyChecksPanel: React.ComponentType<never>;
  Stage2Filters: React.ComponentType<never>;
  RunSummaryPanel: React.ComponentType<never>;
  ResolveCheckDialog: React.ComponentType<never>;
  checkSeverityColor: (s: string) => string;
  checkTypeLabel: (t: string) => string;
}) {
  const p1 = s2PmProps(), { rerender } = ren(React.createElement(C.PendingMatchesPanel, p1 as never));
  has(["1 total", "1 selected"]);
  fireEvent.click(within(tid(S2.card)).getByRole("checkbox", { name: S2.sel1 }));
  fireEvent.click(within(tid(S2.desk)).getByText(S2.sal));
  cN(p1.onToggleMatch, 2); clk("Deselect all"); clk("Reject"); clk(S2.approveSel);
  eq([p1.onToggleAll, p1.onBatchReject, p1.onBatchApprove].map((x) => x.mock.calls.length), [1, 1, 1]);
  rerender(React.createElement(C.PendingMatchesPanel, s2PmProps(s2Parts.pmEmpty) as never)); has([S2.noM]);
  rerender(React.createElement(C.PendingMatchesPanel, s2PmProps(s2Parts.pmScores) as never));
  gt(allTxt("—").length, 0); hasAttr(btn(S2.approveSel), "title", S2.rcFirst);
  for (const [sc, cls] of S2.scoreCls) hasCls(allTxt(sc)[0], cls);
  rerender(React.createElement(C.PendingMatchesPanel, s2PmProps({ actionLoading: true }) as never));
  dis("Processing..."); chk(tid(S2.desk).querySelector("thead input[type='checkbox']"));

  const onRes = vi.fn(), onChg = vi.fn(), onCls = vi.fn(), checks = [mkCheck(), S2.custom];
  const cp = ren(React.createElement(C.ConsistencyChecksPanel, { checks: [], onResolve: onRes } as never)); has(["No pending checks"]);
  cp.rerender(React.createElement(C.ConsistencyChecksPanel, { checks, onResolve: onRes } as never));
  has(["Potential duplicate", JSON.stringify({ reason: "Needs human review" })]);
  fireEvent.click(screen.getAllByRole("button", { name: "Resolve" })[0]); hasC(onRes, checks[0]);

  const f = ren(React.createElement(C.Stage2Filters, { filters: { checkType: "", status: "", severity: ["high"], minScore: 20 }, onChange: onChg } as never));
  clk("HIGH", f.container); clk("MEDIUM", f.container);
  const [ct, st] = within(f.container).getAllByRole("combobox"); chgEl(ct, "anomaly"); chgEl(st, "resolved");
  chgEl(within(f.container).getByRole("slider"), "45"); eq(onChg.mock.calls.map((c) => c[0]), S2.filterCalls);

  const rp1 = s2RunProps(), r = ren(React.createElement(C.RunSummaryPanel, rp1 as never));
  has(S2.res1); clk(S2.approveRun, r.container); cN(rp1.onApproveRun, 1);
  r.rerender(React.createElement(C.RunSummaryPanel, s2RunProps(s2Parts.run2) as never)); has(S2.res2);

  const d = ren(React.createElement(C.ResolveCheckDialog, { check: mkCheck({ details: {} }), actionLoading: false, onClose: onCls, onResolve: onRes } as never));
  const dg = role("dialog", S2.dlg); chgEl(box(dg), "note");
  clk("Flag", dg); clk("Reject", dg); hasC(onRes, "flag", "note"); hasC(onRes, "reject", "note");
  clk("Cancel", dg); fireEvent.click(document.querySelector(S2.overlay) as HTMLElement); esc(); cN(onCls, 3);
  d.rerender(React.createElement(C.ResolveCheckDialog, { check: mkCheck(), actionLoading: true, onClose: onCls, onResolve: onRes } as never)); esc(); cN(onCls, 3);

  eq(["high", "medium", "low"].map((s) => C.checkSeverityColor(s)), S2.sevColors);
  eq(["duplicate", "transfer_pair", "anomaly", "manual_review"].map((t) => C.checkTypeLabel(t)), S2.typeLabels);
}

export async function stmtsPollFlow(api: ApiMock, ui: React.ReactElement, stmt: (id: string, name: string, status: BankStatement["status"]) => BankStatement) {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const p = stmtsPollApi(api, stmt), v = ren(ui);
  await see(STMTS.parsingTitle); await tick(3000); eq(p.reads(), 2);
  const pSig = sigOf(api, OP.STMTS, 1); expect(pSig).toBeInstanceOf(AbortSignal);
  await tick(6000); eq(p.reads(), 2); fireEvent.click(txt(STMTS.upBtn)); await see("ready.pdf");
  aborted(pSig); p.poll.resolve(p.parsing); await p.poll.promise; noTxt("parsing.pdf");
  fireEvent.click(txt(STMTS.upBtn)); await wFor(() => eq(p.reads(), 4));
  const tdSig = sigOf(api, OP.STMTS, 3); v.unmount(); aborted(tdSig); stmtsMockState.onUpload?.();
  p.td.resolve(p.ready); await p.td.promise; await tick(6000); eq(p.reads(), 4);
}

export async function stmtsDelFlow(api: ApiMock, ui: React.ReactElement, toast: ReturnType<typeof vi.fn>, ps: ReturnType<typeof stmtsPresets>) {
  const spy = vi.spyOn(globalThis, "setInterval");
  ps.parsingNull(); const v1 = ren(ui); await see(STMTS.parsingTitle); expect(spy).toHaveBeenCalled();
  txtIs(stRole(), /usually takes ~2–3 minutes/i); isNull(stRole().querySelector('[style*="width: 60%"]')); v1.unmount();
  ps.delOk(); const v2 = ren(ui); await see("delete.pdf");
  fireEvent.click(screen.getByTitle(STMTS.delTitle)); await fTid("confirm-dialog"); clk(STMTS.delBtn);
  await wCall(api, OP.DEL_STMT, { path: { statement_id: "s3" } }); hasC(toast, STMTS.delOk, "success"); v2.unmount();
  ps.delFail(); const v3 = ren(ui); await see("needs-review.pdf");
  has(["No statement period", "Needs Review"]); gte(allTxt("—").length, 1);
  fireEvent.click(screen.getByTitle(STMTS.delTitle)); clk(STMTS.canBtn); isNull(screen.queryByTestId("confirm-dialog"));
  fireEvent.click(screen.getByTitle(STMTS.delTitle)); clk(STMTS.delBtn);
  await wFor(() => gt(allTxt("delete failed").length, 0)); v3.unmount();
  toast.mockClear(); ps.empty(); ren(ui); await see(STMTS.noStmts); api.mockClear();
  clk(STMTS.noSelBtn); expect(api).not.toHaveBeenCalled(); expect(toast).not.toHaveBeenCalled();
}

export async function upErrStorageChecks(ui: React.ReactElement, up: ReturnType<typeof vi.fn>, tr: ReturnType<typeof vi.fn>, evFailed: string, put: (f: File | File[], k?: string) => Promise<void>) {
  up.mockRejectedValueOnce(new Error("Server Error")); ren(ui);
  await put(UP.pdf()); clk(/upload & parse/i); await see("Server Error");
  hasC(tr, evFailed, expect.objectContaining({ error_category: "error" }));
  checkCallsNoSecret(tr.mock.calls, "Server Error");
}

export async function revNavAndOriginFlows(n: { reset: () => void }, renP: () => { unmount: () => void }, nav: { push: ReturnType<typeof vi.fn>; searchParams: URLSearchParams }, trackFn: unknown, ev: string) {
  n.reset(); const v1 = renP();
  await fClk("← Prev"); clk("Next →"); hasC(nav.push, "/statements/s0"); hasC(nav.push, "/statements/s2");
  await approveStmt(); await see(REV.approvedMsg); hasC(trackFn, ev, expect.objectContaining({ statement_id: "s1" })); noBtn("Approve"); v1.unmount();
  n.reset(); const v2 = renP(); await rejectFlow("Needs re-parse"); await see("Parsing Failed"); has([REV.rejBy]);
  inDoc(btn("Run again")); noBtn("Retry Parse"); v2.unmount();
  n.reset(); nav.searchParams = new URLSearchParams("from=attention"); renP();
  await fHasLnk(REV.backAtt, REV.attUrl); await approveStmt(); await wCall(nav.push, REV.attUrl);
}

export async function revAutoFillFlows(mv: ReturnType<typeof revMocks>, renP: (m?: "unrated") => { unmount: () => void }, ApiErr: new (m: string, s: number) => Error) {
  const b1 = mv.econ409(ApiErr), v1 = renP();
  await approveStmt(); await see(REV.econMsg); await fHasLnk("Review transaction classifications", REV.prevUrl); await fHasLnk("Review AI suggestions", REV.aiUrl);
  await fClk(REV.autoFillBtn); await wFor(() => mObj(b1(), { auto_fill_default_categories: true })); v1.unmount();
  const v2 = renP("unrated"); await wValIs(() => lbl(REV.custLbl), "acc-dbs"); v2.unmount();
  const b2 = mv.unratedApprove(); renP(); await see(REV.unratedMsg); inDoc(btn(REV.autoFillBtn));
  await fClk("Approve"); const d = await dlg(REV.confDlg); has([REV.autoMsg], d); clk("Approve", d);
  await wFor(() => mObj(b2(), { auto_fill_default_categories: true }));
}

export async function unmErrCoexistFlows(api: ApiMock, ui: React.ReactElement) {
  mockApiSeq(api, ...unmSeq.err); const v1 = ren(ui); await unmFill();
  const f1 = unmDlg(); clk(UNM.createAcc, f1); inDoc(await within(f1).findByText(UNM.dupErr));
  clk("Cancel", f1); noDlg(); valIs(lbl(UNM.rc), "DINING"); dis(UNM.postBtn); v1.unmount();
  mockApiSeq(api, ...unmSeq.usd); const v2 = ren(ui); await fChg(UNM.tt, "expense");
  clk(UNM.createAcc, unmDlg("Create counter account", "Dining", "USD")); await wFor(() => noDlg());
  noRole("option", /Expense - Dining/); dis(UNM.postBtn); v2.unmount();
  mockApiSeq(api, ...unmSeq.scoped.slice(0, 2)); api.mockResolvedValueOnce(UNM.secAcc as never); ren(ui); await fChg(UNM.tt, "expense");
  clk(UNM.createAcc, unmDlg("+ Create counter account", UNM.secAcc.name)); await wFor(() => noDlg());
  inDoc(role("option", /Expense - Dining/)); inDoc(role("option", /Expense - Utilities/));
}

export async function unmMultiScopedFlows(api: ApiMock, ui: React.ReactElement, nav: { searchParams: URLSearchParams }) {
  mockApiSeq(api, ...unmSeq.multi); const v0 = ren(ui); await fRole("heading", "Unmatched Transactions");
  clk(/Salary/); valIs(await fLbl(UNM.tt), "unknown"); chg(UNM.tt, "income");
  inDoc(await fRole("option", /Income - Salary/)); noRole("option", /Expense - Dining/);
  clk(/Card payment/); chg(UNM.tt, "transfer"); has([UNM.xferMsg]); noBtn(UNM.postBtn);
  chg(UNM.tt, "unknown"); has([UNM.unkMsg]); await unmFill("expense", UNM.exp.id); clk(UNM.postBtn);
  await wCall(api, OP.UNM_POST, { path: { txn_id: "u1" }, body: UNM.postBody });
  txtIs((await fTxt("je1")).parentElement!, "Posted reviewed entry je1"); noBtn(/Create Entry/i); v0.unmount();

  api.mockReset(); nav.searchParams = new URLSearchParams("statement_id=s1&return_to=%2Fstatements%2Fs1");
  const d = deferred<{ items: (typeof UNM.item)[]; total: number }>();
  mockApiSeq(api, ...unmSeq.scoped); api.mockReturnValueOnce(d.promise as never).mockResolvedValueOnce({ items: [UNM.exp], total: 1 } as never);
  const v1 = ren(ui); await wCall(api, OP.UNM_LIST, { query: expect.objectContaining({ statement_id: "s1" }) });
  await unmFill("expense", UNM.exp.id); clk(UNM.postBtn); await wFor(() => cN(api, 5));
  noRole("link", UNM.retLnk); d.resolve({ items: [], total: 0 }); await see(UNM.doneTxt); hasLnk(UNM.retLnk, "/statements/s1"); v1.unmount();

  api.mockReset(); mockApiSeq(api, ...unmSeq.scoped.slice(0, 2)); api.mockRejectedValueOnce(new Error(UNM.incompErr));
  const v2 = ren(ui); await unmFill("expense", UNM.exp.id); clk(UNM.postBtn);
  await see(UNM.incompErr); noTxt(/Posted reviewed entry/); v2.unmount();

  api.mockReset(); mockApiSeq(api, ...unmSeq.precise); ren(ui);
  await wFor(() => len(allTxt("$12,345,678,901,234,567,890.12"), 2));
}

export async function wbErrRefreshLinksFlows(api: ApiMock, ui: React.ReactElement) {
  for (const [op, msg, exp] of WB.qErrs) { mockWbApi(api, { [op]: () => Promise.reject(new Error(msg)) }); const v = ren(ui); await see(exp); v.unmount(); }
  wbErrApi(api); const v3 = ren(ui); await see("Rent");
  for (const [b, err] of WB.mErrs) { clk(b); await see(err); } v3.unmount();
  mockWbApi(api, wbPresets.seq()); const v4 = ren(ui); await wFor(() => gt(allTxt("800.00").length, 0));
  clk(WB.runM); await see("825.00"); clk(WB.runM); await see(WB.emptyMsgs[0]); has(WB.emptyMsgs); v4.unmount();
  mockWbApi(api, wbPresets.links); ren(ui); const nv = await fRole("navigation", WB.navLbl);
  hasAttr(within(nv).getByRole("link", { name: "Matches" }), "aria-current", "page");
  inDoc(await within(within(nv).getByRole("link", { name: /Unmatched/i })).findByText("3"));
  await wFor(() => hasAttr(lnk(WB.srcSt), "href", "/statements/stmt-42"));
  clk(/Utilities/i); await wFor(() => hasAttr(lnk(WB.srcLnk), "href", "/upload"));
}

export async function aiQueueLockFlow(api: ApiMock, ui: React.ReactElement) {
  const p = deferred<unknown>(); mockApiSeq(api, ...AI.fbSeq); api.mockReturnValueOnce(p.promise as never); ren(ui);
  const c = within(await fTid(AI.mobList)).getByTestId(`ai-suggestion-mobile-card-${AI.id}`), w = within(c);
  has(AI.cardInfo, c); expect(w.getByRole("status")).toBeEmptyDOMElement();
  const sel = w.getByLabelText(AI.corrLbl) as HTMLSelectElement, opts = Array.from(sel.options).map((o) => o.value);
  expect(opts).toEqual(expect.arrayContaining(AI.opts)); expect(opts).not.toContain("SALARY");
  clk("Accept", c); await w.findByText(/^Accepted\./);
  clk("Reject", c); txtIs(await w.findByRole("status"), AI.rejNote);
  chgEl(sel, "TRANSPORT"); clk(AI.editBtn, c); await w.findByText(/^Corrected\./); expect(api).toHaveBeenCalledWith(OP.AI_FB, AI.fbBody);
  clk("Accept", c); await wFor(() => txtIs(w.getByRole("status"), AI.noChange));
  chgEl(sel, "SALARY"); clk(AI.editBtn, c); txtIs(await w.findByRole("alert"), AI.sugErr);
  clk("Reject", c); await see("Saving...", c); for (const n of AI.acts) dis(n, c);
  clk("Reject", c); cN(api, 7); p.resolve({ id: "f5", effect: "rejected" }); await w.findByText(/^Rejected\./); en("Accept", c);
}

export async function lowModalCloseFlow(api: ApiMock, toast: ReturnType<typeof vi.fn>, push: ReturnType<typeof vi.fn>, M: (o?: Record<string, unknown>) => React.ReactElement, chatKey: string) {
  const p = deferred<unknown>(), onClose = vi.fn(); (api as unknown as { mockReturnValueOnce: (v: unknown) => void }).mockReturnValueOnce(p.promise);
  const { rerender } = ren(M({ onClose }));
  clk(LOW.ask); expect(sessionStorage.getItem(chatKey)).toContain(LOW.prompt);
  hasC(push, "/chat"); for (const l of LOW.noLbls) noLbl(l); noBtn("Salary");
  clk("Dining"); sub(lbl(LOW.cat)); await wDis(/Saving/i); sub(lbl(LOW.cat)); esc(); clk(LOW.cls); cN(api, 1); cN(onClose, 0);
  p.resolve({ id: "c1" }); await wCall(toast, LOW.ok, "success"); esc(); clk(LOW.cls); cN(onClose, 3);
  rerender(M({ onClose, transaction: LOW.inTxn })); expect([btn("Salary"), btn("Transfer")]).toBeTruthy(); noBtn("Dining"); valIs(lbl(LOW.cat), "SALARY");
  rerender(M({ isOpen: false, onClose })); esc(); cN(onClose, 3);
}

export async function evPanelMobileFlow(api: ApiMock, mv: (l?: Parameters<typeof mockValApi>[1], p?: Promise<unknown>) => void, G: (o?: Record<string, unknown>) => React.ReactElement, scCfg: { value: string }[], vbo: unknown[]) {
  mockMM(); mv(EV.snaps); const v1 = ren(G({ initialSourceClass: "liability_statement" }));
  txtIs(tid(EV.badge), "Manual-trusted"); valIs(lbl(EV.sc), "liability_statement");
  inDoc(role("form", "Guided evidence form")); expect(lbl(EV.val)).toBeVisible();
  const p = await fTid(EV.panel); await within(p).findAllByText(EV.srcTxt);
  gt(within(p).getAllByText("Manual-trusted").length, 0);
  inDoc(within(p).getByText(EV.emp)); len(within(p).getAllByText(/·/), 1); v1.unmount();
  Object.defineProperty(window, "matchMedia", { configurable: true, writable: true, value: undefined }); mv();
  ren(G({ initialSourceClass: "unknown_class" }));
  valIs(lbl(EV.sc), "esop_rsu_plan"); await see(EV.none);
  eq(scCfg.map((c) => c.value), EV.classes); len(vbo, 7);
}

export function txnOrderFlow(T: (txns: unknown, o?: Record<string, unknown>) => React.ReactElement, normFn: (b: unknown) => { transactions: Record<string, unknown>[] }, vmFn: (r: unknown) => Record<string, unknown>) {
  const reg = () => tid(TXN.desk), titles = () => within(reg()).getAllByRole("row").slice(1).map((tr) => tr.querySelector("[title]")?.getAttribute("title"));
  const { status: _, ...noSt } = TXN.sample[0]; void _;
  const { rerender } = ren(T(TXN.sample)); noTxt("pending");
  rerender(T(TXN.sample, { statementStatus: "parsed" }));
  noRole("columnheader", "Status"); has(["pending"], within(reg()).getByTitle("Coffee").closest("td") as HTMLElement);
  rerender(T([mkTxn({ id: "u", status: "unmatched" }), { ...noSt, id: "d" }], { statementStatus: "parsed" }));
  has(["unmatched", "pending"]); noTxt("matched");
  const norm = normFn(TXN.normInput);
  for (const txns of [norm.transactions, norm.transactions.map((t) => ({ ...t, status: "pending" as const }))]) {
    rerender(T(txns, { statementStatus: "approved" })); noTxt("pending"); len(allTxt("matched"), 2);
  }
  rerender(T(TXN.multi)); eq(titles(), TXN.multiTitles); has(["6 total · in statement order"]); txtIs(tid(TXN.lowCnt), TXN.lowMsg2);
  const cards = within(tid(TXN.mobList)).getAllByRole("article");
  eq(cards.map((c) => c.getAttribute("data-testid")?.replace("stage1-mobile-transaction-card-", "")), TXN.mobIds);
  txtIs(within(cards[1]).getByTestId(TXN.rowNum), TXN.row6); isNull(within(cards[2]).queryByTestId(TXN.rowNum));
  rerender(T(TXN.wire.map((r) => vmFn(r)))); eq(titles(), TXN.wireTitles);
  const unrated = vmFn(TXN.unratedRaw); eq([unrated.confidence_tier, unrated.confidence], [null, undefined]);
  rerender(T([unrated, mkTxn({ id: "h", description: "Salary", confidence_tier: "HIGH" }), mkTxn({ id: "l", description: "Fee", confidence_tier: "LOW" })]));
  eq(titles(), TXN.unratedTitles); const rows = within(reg()).getAllByRole("row").slice(1);
  hasCls(within(rows[1]).getByText("Not rated"), "badge-muted"); isNull(within(rows[1]).queryByText(/low/i));
  txtIs(tid(TXN.lowCnt), TXN.lowMsg1); rerender(T([mkTxn({ confidence_tier: "HIGH" })])); isNull(screen.queryByTestId(TXN.lowCnt));
}

export async function upCsvBatchFlow(renderWithCb: (cb: () => void) => void, up: ReturnType<typeof vi.fn>, tr: ReturnType<typeof vi.fn>, vec: { status: unknown; transactions: unknown }, ev: { start: string; ok: string }, put: (f: File | File[]) => Promise<void>) {
  eq([vec.status, vec.transactions], ["parsing", []]);
  up.mockResolvedValue(vec); const onDone = vi.fn(); renderWithCb(onDone);
  clk(/upload & parse/i); await see(UP.noFile);
  await put(UP.csv()); noLbl(UP.aiLbl); inDoc(txt(UP.csvMsg));
  clk(/upload & parse/i); await wCall(up, UP.upOp, { body: expect.any(FormData) });
  isNull((up.mock.calls[0]?.[1].body as FormData).get("model")); cN(onDone, 1);
  const dz = txt(UP.dzPrompt).closest(".card")!;
  fireEvent.dragOver(dz); hasCls(dz, UP.dzCls); fireEvent.dragLeave(dz); noCls(dz, UP.dzCls);
  fireEvent.drop(dz, { dataTransfer: { files: [UP.png()] } }); await see("statement.png");
  up.mockClear(); tr.mockClear(); await put(UP.pdf("secret.pdf")); clk(/upload & parse/i);
  await wCall(tr, ev.ok, expect.objectContaining({ is_csv: false }));
  hasC(tr, ev.start, expect.objectContaining({ is_csv: false }));
  checkCallsNoSecret(tr.mock.calls, "secret.pdf");
  up.mockClear(); await put([UP.csv("oct.csv", "x"), UP.csv("nov.csv", "x")]);
  clk(/upload & parse/i); await wFor(() => cN(up, 2));
}

export async function clsMetaPollFlow(api: ApiMock, setup: (r: () => StatementRun[], ex?: Record<string, unknown>, post?: () => Promise<unknown>) => { unmount: () => void }) {
  const v1 = setup(() => [mkRun({ seq: 1, state: "running", finished_at: null })]);
  await fTid(CLS.pa); await wDis("Approve"); dis(CLS.auto); noTxt(CLS.notice); v1.unmount();
  const v2 = setup(() => [mkRun({ seq: 1 }), mkClassifyRun("running")], CLS.env, () => Promise.resolve({ id: "env-1" }));
  await see(CLS.notice); await fChg(CLS.why, "Checked."); await wEn(CLS.cfBtn); clk(CLS.cfBtn); await wCnt(api, OP.CONFIRM, 1); v2.unmount();
  vi.useFakeTimers({ shouldAdvanceTime: true }); let st: StatementRun["state"] = "running";
  setup(() => [mkRun({ seq: 1 }), mkClassifyRun(st)]); await see(CLS.notice); await wDis("Approve");
  const rb = cnt(api, OP.REV), sb = cnt(api, OP.STMT); st = "succeeded"; await tick(3100); await wNoTxt(CLS.notice);
  await wEn("Approve"); await wEn(CLS.auto); await wGt(api, OP.REV, rb); await wGt(api, OP.STMT, sb);
  has(["Extract"], tid(CLS.pa1)); has(["Classify", "System · Auto Classify", "Succeeded"], tid(CLS.pa2));
}

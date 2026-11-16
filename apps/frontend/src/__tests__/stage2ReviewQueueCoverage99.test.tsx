import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ConsistencyChecksPanel,
  PendingMatchesPanel,
  ResolveCheckDialog,
  RunSummaryPanel,
  Stage2Filters,
  Stage2ReviewQueue,
} from "@/components/review/Stage2ReviewQueue";
import { checkSeverityColor, checkTypeLabel } from "@/lib/statusLabels";
import type { ConsistencyCheck, PendingMatch } from "@/lib/types"; import { apiOperation } from "@/lib/api-client"; import { renderReviewComponent } from "./helpers/renderReviewComponent"; const runIdState = vi.hoisted(() => ({ current: null as string | null })); const navState = vi.hoisted(() => ({ pathname: "/reconciliation", replace: vi.fn(), push: vi.fn(), searchParams: new URLSearchParams(), })); vi.mock("@/lib/api-client", () => ({ apiOperation: vi.fn() })); vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: navState.replace, push: navState.push }), useSearchParams: () => navState.searchParams, usePathname: () => navState.pathname, })); function mapStage2OperationToLegacy(operationId: string, req: any = {}): [string, RequestInit | undefined] { switch (operationId) { case "get_stage2_review_queue_statements_stage2_queue_get": { const q = req?.query; let path = "/api/statements/stage2/queue"; if (q) { const params = new URLSearchParams(); for (const [k, v] of Object.entries(q)) { if (v !== undefined && v !== null) params.append(k, String(v)); }; const qs = params.toString(); if (qs) path += `?${qs}`; }; return [path, undefined]; }
case "list_consistency_checks_statements_consistency_checks_list_get": return ["/api/statements/consistency-checks/list", undefined]; case "batch_approve_matches_statements_batch_approve_matches_post": return ["/api/statements/batch-approve-matches", { method: "POST", body: JSON.stringify(req?.body) }]; case "batch_reject_matches_statements_batch_reject_matches_post": return ["/api/statements/batch-reject-matches", { method: "POST", body: JSON.stringify(req?.body) }]; case "resolve_consistency_check_statements_consistency_checks__check_id__resolve_post": return [`/api/statements/consistency-checks/${req?.path?.check_id ?? "c1"}/resolve`, { method: "POST", body: JSON.stringify(req?.body) }]; case "get_processing_summary_accounts_processing_summary_get": return ["/api/accounts/processing/summary", undefined]; default: return [operationId, req]; } }; const mockedApiFetch = vi.mocked(apiOperation); const originalMockImplementation = mockedApiFetch.mockImplementation.bind(mockedApiFetch)
mockedApiFetch.mockImplementation = (fn: any) => { return originalMockImplementation((operationId: any, req: any) => { if (typeof operationId === "string" && operationId.startsWith("/")) { return fn(operationId, req) }; const [path, options] = mapStage2OperationToLegacy(operationId, req); return fn(path, options) }) }; const originalMatchMedia = window.matchMedia
const pendingMatch = { id: "m1", match_score: 88, confidence_tier: "HIGH", status: "pending_review", created_at: "2026-01-01T00:00:00Z", description: "Salary transfer", amount: "1200", txn_date: "2026-01-01", }; const lowMatch = { id: "m2", match_score: 55, confidence_tier: "HIGH", status: "pending_review", created_at: "2026-01-02T00:00:00Z", description: "Low confidence transfer", amount: null, txn_date: null, }; const duplicateCheck = { id: "c1", check_type: "duplicate", status: "pending", related_txn_ids: [], details: { message: "Potential duplicate" }, severity: "high", resolved_at: null, resolution_note: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", }; const customCheck = { id: "c2", check_type: "manual_review", status: "pending", related_txn_ids: [], details: { reason: "Needs human review" }, severity: "low", resolved_at: null, resolution_note: null, created_at: "2026-01-02T00:00:00Z", updated_at: "2026-01-02T00:00:00Z", }; function queue(overrides: Partial<{ pending_matches: unknown[]
consistency_checks: unknown[]
has_unresolved_checks: boolean }> = {}) { return { pending_matches: [pendingMatch], consistency_checks: [], has_unresolved_checks: false, ...overrides, } }; function mockApi( q: unknown = queue(), summary: unknown = { pending_count: 0, pending_total: "0", currency: "SGD", oldest_pending_date: null }, checks: unknown[] = [], extra?: (path: string, options?: RequestInit) => Promise<unknown> | undefined, ) { const sum = summary ?? { pending_count: 0, pending_total: "0", currency: "SGD", oldest_pending_date: null }
mockedApiFetch.mockImplementation((path: string, options?: RequestInit) => { if (extra) { const res = extra(path, options); if (res !== undefined) return res as never }; if (path.startsWith("/api/statements/stage2/queue")) return Promise.resolve(q as never); if (path === "/api/accounts/processing/summary") return (sum instanceof Promise ? sum : Promise.resolve(sum)) as never
if (path.startsWith("/api/statements/consistency-checks/list")) return Promise.resolve({ items: checks } as never); if (path.includes("/resolve")) return Promise.resolve({ success: true } as never); if (path.includes("batch-approve-matches")) return Promise.resolve({ success: true, approved_count: 1 } as never); if (path.includes("batch-reject-matches")) return Promise.resolve({ success: true, rejected_count: 1 } as never); return Promise.reject(new Error(`Unexpected path ${path}`)) }) }; function mockMobileViewport() { Object.defineProperty(window, "matchMedia", { configurable: true, writable: true, value: vi.fn().mockImplementation((query: string) => ({ matches: true, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(), })), }) }; const Queue = () => <Stage2ReviewQueue runId={runIdState.current} />
describe("AC8.13.48 Stage2ReviewQueue frontend coverage lift", () => { beforeEach(() => { mockedApiFetch.mockReset()
navState.pathname = "/reconciliation"
runIdState.current = null
navState.searchParams = new URLSearchParams()
navState.replace.mockReset()
navState.push.mockReset() }); afterEach(() => { Object.defineProperty(window, "matchMedia", { configurable: true, writable: true, value: originalMatchMedia, }) }); it("AC8.13.76/AC16.26.2 mobile queue renders selectable match cards and batch actions", async () => { mockMobileViewport()
mockApi(queue({ pending_matches: [pendingMatch] }))
renderReviewComponent(<Queue />); const card = await screen.findByTestId("stage2-mobile-match-card-m1"); expect(within(card).getByText("Salary transfer")).toBeInTheDocument(); fireEvent.click(within(card).getByRole("checkbox", { name: "Select match m1" })); await waitFor(() => expect(screen.getByText("1 selected")).toBeInTheDocument()); expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled(); expect(screen.getByRole("button", { name: "Approve Selected" })).toBeEnabled() }); it("AC22.11.3 keeps the tab and the attention origin in the URL while the Stage 2 queue updates filters", async () => { navState.searchParams = new URLSearchParams("tab=review-queue&from=attention&min_score=0")
mockApi(queue({ pending_matches: [] }))
renderReviewComponent(<Queue />); await waitFor(() => expect(navState.replace).toHaveBeenCalledWith("/reconciliation?tab=review-queue&from=attention", { scroll: false, }), ) }); it("AC16.26.3 mobile run review preserves approval gate and pending match workflow", async () => { mockMobileViewport()
runIdState.current = "mobile-run"
mockApi(queue({ pending_matches: [pendingMatch] }))
renderReviewComponent(<Queue />); expect(await screen.findByText("Run approval gate")).toBeInTheDocument(); expect(screen.getByRole("button", { name: "Approve Run" })).toBeEnabled(); expect(await screen.findByTestId("stage2-mobile-match-card-m1")).toBeInTheDocument() }); it("keeps desktop table and mobile first-paint markup when matchMedia is unavailable", async () => { Object.defineProperty(window, "matchMedia", { configurable: true, writable: true, value: undefined, })
mockApi(queue({ pending_matches: [pendingMatch] }))
renderReviewComponent(<Queue />); expect(await screen.findByText("Pending Matches")).toBeInTheDocument(); expect(screen.getByTestId("stage2-mobile-match-card-m1")).toBeInTheDocument(); expect(screen.getAllByText("Salary transfer").length).toBeGreaterThan(0) }); it("AC16.27.1 keeps mobile pending-match cards in the DOM without matchMedia gating", async () => { Object.defineProperty(window, "matchMedia", { configurable: true, writable: true, value: undefined, })
mockApi(queue({ pending_matches: [pendingMatch] }))
renderReviewComponent(<Queue />); expect(await screen.findByTestId("stage2-mobile-match-card-m1")).toBeInTheDocument(); expect(screen.getAllByText("Salary transfer").length).toBeGreaterThan(0) }); it("AC8.13.82/AC16.27.3 exposes a fixed desktop pending-match region for responsive UX proofs", async () => { mockApi(queue({ pending_matches: [pendingMatch] }))
renderReviewComponent(<Queue />); const region = await screen.findByTestId("stage2-desktop-match-region"); expect(region).toHaveClass("overflow-hidden"); const table = region.querySelector("table"); expect(table).toHaveClass("table-fixed", "border-collapse"); expect(table).toHaveStyle({ width: "calc(100% - 4px)" }) }); it("AC16.23.4/AC8.13.48 persists Stage 2 filters in the URL while approving after filter changes", async () => { runIdState.current = "run 1"
navState.searchParams = new URLSearchParams("check_type=duplicate&status=pending&severity=high,medium&min_score=60")
mockApi(queue({ pending_matches: [pendingMatch, lowMatch], consistency_checks: [] }), undefined, [], (path, options) => { if (path === "/api/statements/batch-approve-matches") { expect(options).toMatchObject({ method: "POST", body: JSON.stringify({ match_ids: ["m1", "m2"] }) }); return Promise.resolve({ success: true, approved_count: 2 }) } })
renderReviewComponent(<Queue />); expect(await screen.findByText("Review queue")).toBeInTheDocument(); expect(screen.getByText("run 1")).toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "HIGH" })); const [checkTypeSelect, statusSelect] = screen.getAllByRole("combobox"); fireEvent.change(checkTypeSelect, { target: { value: "anomaly" } }); fireEvent.change(statusSelect, { target: { value: "resolved" } }); fireEvent.click(screen.getByRole("button", { name: "Select all" })); await waitFor(() => expect(screen.getByText("1 selected")).toBeInTheDocument()); fireEvent.click(screen.getByRole("button", { name: "Deselect all" })); await waitFor(() => expect(screen.getByText("0 selected")).toBeInTheDocument()); fireEvent.click(screen.getByRole("button", { name: "Approve Run" })); await waitFor(() => { expect(mockedApiFetch).toHaveBeenCalledWith( "batch_approve_matches_statements_batch_approve_matches_post", expect.anything(), ) }); await waitFor(() => { expect(navState.replace).toHaveBeenCalledWith( "/reconciliation?check_type=anomaly&status=resolved&severity=medium&min_score=60", { scroll: false }, ) }) }); it("test_AC8_13_48_dialog_dismissal_and_resolution_error_paths", async () => { mockedApiFetch.mockImplementation((path: string) => { if (path.startsWith("/api/statements/stage2/queue")) { return Promise.resolve(queue({ consistency_checks: [customCheck], has_unresolved_checks: true }) as never) }; if (path.startsWith("/api/statements/consistency-checks/list")) { return Promise.reject(new Error("filter failed")) }; if (path === "/api/statements/consistency-checks/c2/resolve") { return Promise.reject(new Error("resolve failed")) }; return Promise.reject(new Error(`Unexpected path ${path}`)) })
renderReviewComponent(<Queue />); expect(await screen.findByText("manual_review")).toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "Resolve" })); expect(await screen.findByRole("dialog", { name: "Resolve Consistency Check" })).toBeInTheDocument(); fireEvent.keyDown(document, { key: "Escape" }); await waitFor(() => expect(screen.queryByRole("dialog", { name: "Resolve Consistency Check" })).not.toBeInTheDocument()); fireEvent.click(screen.getByRole("button", { name: "Resolve" })); const overlay = document.querySelector(".fixed.inset-0[aria-hidden='true']") as HTMLElement
fireEvent.click(overlay); await waitFor(() => expect(screen.queryByRole("dialog", { name: "Resolve Consistency Check" })).not.toBeInTheDocument()); fireEvent.click(screen.getByRole("button", { name: "Resolve" })); const dialog = await screen.findByRole("dialog", { name: "Resolve Consistency Check" }); fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Keep reviewing" } }); fireEvent.click(within(dialog).getByRole("button", { name: "Reject" })); await waitFor(() => { expect(mockedApiFetch).toHaveBeenCalledWith( "resolve_consistency_check_statements_consistency_checks__check_id__resolve_post", expect.objectContaining({ path: { check_id: "c2" }, body: { action: "reject", note: "Keep reviewing" }, }), ) }); const cancelButton = within(dialog).getByRole("button", { name: "Cancel" }); await waitFor(() => expect(cancelButton).toBeEnabled()); fireEvent.click(cancelButton); await waitFor(() => expect(screen.queryByRole("dialog", { name: "Resolve Consistency Check" })).not.toBeInTheDocument()) }); it("test_AC8_13_48_batch_and_run_error_branches_surface_actionable_feedback", async () => { runIdState.current = "run-2"
mockApi(queue({ pending_matches: [pendingMatch], consistency_checks: [] }), undefined, [], (path) => { if (path === "/api/statements/batch-approve-matches") return Promise.reject(new Error("approval rejected by server")); if (path === "/api/statements/batch-reject-matches") return Promise.reject(new Error("batch reject failed")) })
renderReviewComponent(<Queue />); expect(await screen.findByText("Review queue")).toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "Select all" })); fireEvent.click(screen.getByRole("button", { name: "Approve Selected" })); await waitFor(() => { expect(mockedApiFetch).toHaveBeenCalledWith( "batch_approve_matches_statements_batch_approve_matches_post", expect.anything(), ) }); const rejectButton = screen.getByRole("button", { name: "Reject" }); await waitFor(() => expect(rejectButton).toBeEnabled()); fireEvent.click(rejectButton); await waitFor(() => { expect(mockedApiFetch).toHaveBeenCalledWith( "batch_reject_matches_statements_batch_reject_matches_post", expect.anything(), ) }); const approveRunButton = await screen.findByRole("button", { name: "Approve Run" }); await waitFor(() => expect(approveRunButton).toBeEnabled()); fireEvent.click(approveRunButton); await waitFor(() => { const approveCalls = mockedApiFetch.mock.calls.filter((call) => (call[0] as string) === "batch_approve_matches_statements_batch_approve_matches_post" || (call[0] as string) === "/api/statements/batch-approve-matches"); expect(approveCalls.length).toBeGreaterThanOrEqual(2) }) }); it("test_AC8_13_48_filters_checks_and_toggles_individual_match_selection", async () => { runIdState.current = "run-3"
mockApi( queue({ pending_matches: [pendingMatch], consistency_checks: [duplicateCheck, customCheck] }), Promise.reject(new Error("processing summary failed")), [duplicateCheck, customCheck], )
renderReviewComponent(<Queue />); expect(await screen.findByText("Review queue")).toBeInTheDocument(); expect(await screen.findByText("manual_review")).toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "HIGH" })); await waitFor(() => expect(screen.queryByText("manual_review")).not.toBeInTheDocument()); expect(screen.getAllByText("Duplicate").length).toBeGreaterThan(0); const desktopMatches = within(screen.getByTestId("stage2-desktop-match-region")); fireEvent.click(desktopMatches.getByText("Salary transfer")); await waitFor(() => expect(screen.getByText("1 selected")).toBeInTheDocument()); fireEvent.click(desktopMatches.getByText("Salary transfer")); await waitFor(() => expect(screen.getByText("0 selected")).toBeInTheDocument()) }); it("test_AC8_13_48_run_approval_guard_states_explain_disabled_actions", async () => { runIdState.current = "run-4"
mockApi(queue({ pending_matches: [pendingMatch], consistency_checks: [duplicateCheck], has_unresolved_checks: true }), undefined, [duplicateCheck]); const first = renderReviewComponent(<Queue />); const unresolvedButton = await screen.findByRole("button", { name: "Approve Run" }); expect(unresolvedButton).toBeDisabled(); expect(unresolvedButton).toHaveAttribute("title", "Resolve consistency checks first")
first.unmount()
mockedApiFetch.mockReset()
mockApi(queue({ pending_matches: [pendingMatch], consistency_checks: [] }), { pending_count: 1, pending_total: "10", currency: "SGD", oldest_pending_date: "2026-01-01" }); const second = renderReviewComponent(<Queue />); const processingButton = await screen.findByRole("button", { name: "Approve Run" }); expect(processingButton).toBeDisabled(); expect(processingButton).toHaveAttribute("title", "Clear Processing Account pending transfers first")
second.unmount()
mockedApiFetch.mockReset()
mockApi(queue({ pending_matches: [], consistency_checks: [] }))
renderReviewComponent(<Queue />); const emptyButton = await screen.findByRole("button", { name: "Approve Run" }); expect(emptyButton).toBeDisabled(); expect(emptyButton).toHaveAttribute("title", "No pending matches remain") }); it("test_AC8_13_48_run_approval_network_errors_are_reported", async () => { runIdState.current = "run-5"
mockApi(queue({ pending_matches: [pendingMatch], consistency_checks: [] }), undefined, [], (path) => { if (path === "/api/statements/batch-approve-matches") return Promise.reject(new Error("approve run failed")) })
renderReviewComponent(<Queue />); fireEvent.click(await screen.findByRole("button", { name: "Approve Run" })); await waitFor(() => { expect(mockedApiFetch).toHaveBeenCalledWith( "batch_approve_matches_statements_batch_approve_matches_post", expect.anything(), ) }); expect(await screen.findByText("approve run failed")).toBeInTheDocument() }) })

function makePartMatch(overrides: Partial<PendingMatch> = {}): PendingMatch {
  return { id: "m1", match_score: 88, confidence_tier: "HIGH", status: "pending_review", created_at: "2026-01-01T00:00:00Z", description: "Salary transfer", amount: "1200.00", txn_date: "2026-01-01", ...overrides };
}
function makePartCheck(overrides: Partial<ConsistencyCheck> = {}): ConsistencyCheck {
  return { id: "c1", check_type: "duplicate", status: "pending", related_txn_ids: [], details: { message: "Potential duplicate" }, severity: "high", resolved_at: null, resolution_note: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", ...overrides };
}
describe("Stage2 extracted parts", () => {
  it("AC22.17.2 PendingMatchesPanel renders mobile + desktop rows and wires selection/batch callbacks", () => {
    const onToggleMatch = vi.fn(), onToggleAll = vi.fn(), onBatchReject = vi.fn(), onBatchApprove = vi.fn();
    render(<PendingMatchesPanel matches={[makePartMatch()]} selectedMatches={new Set(["m1"])} actionLoading={false} hasUnresolvedChecks={false} onToggleMatch={onToggleMatch} onToggleAll={onToggleAll} onBatchReject={onBatchReject} onBatchApprove={onBatchApprove} />);
    expect(screen.getAllByText("1200.00").length).toBeGreaterThan(0);
    expect(screen.getByText("1 total")).toBeInTheDocument();
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    fireEvent.click(within(screen.getByTestId("stage2-mobile-match-card-m1")).getByRole("checkbox", { name: "Select match m1" }));
    expect(onToggleMatch).toHaveBeenCalledWith("m1");
    fireEvent.click(within(screen.getByTestId("stage2-desktop-match-region")).getByText("Salary transfer"));
    expect(onToggleMatch).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("button", { name: "Deselect all" }));
    expect(onToggleAll).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(onBatchReject).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Approve Selected" }));
    expect(onBatchApprove).toHaveBeenCalledTimes(1);
  });
  it("AC22.17.2 PendingMatchesPanel covers empty, loading, dashes, score colors, and disabled approve", () => {
    const { rerender, unmount } = render(<PendingMatchesPanel matches={[]} selectedMatches={new Set()} actionLoading={false} hasUnresolvedChecks={false} onToggleMatch={vi.fn()} onToggleAll={vi.fn()} onBatchReject={vi.fn()} onBatchApprove={vi.fn()} />);
    expect(screen.getByText("No pending matches")).toBeInTheDocument();
    expect(screen.getByText("0 total")).toBeInTheDocument();
    const matches = [makePartMatch({ id: "high", match_score: 90, amount: "10.00" }), makePartMatch({ id: "mid", match_score: 70, amount: undefined, txn_date: undefined, description: undefined }), makePartMatch({ id: "low", match_score: 30, amount: "5.00" })];
    rerender(<PendingMatchesPanel matches={matches} selectedMatches={new Set(["high", "mid", "low"])} actionLoading={false} hasUnresolvedChecks onToggleMatch={vi.fn()} onToggleAll={vi.fn()} onBatchReject={vi.fn()} onBatchApprove={vi.fn()} />);
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Approve Selected" })).toHaveAttribute("title", "Resolve consistency checks first");
    expect(screen.getAllByText("90")[0]).toHaveClass("text-[var(--success)]");
    expect(screen.getAllByText("70")[0]).toHaveClass("text-[var(--warning)]");
    expect(screen.getAllByText("30")[0]).toHaveClass("text-[var(--error)]");
    rerender(<PendingMatchesPanel matches={[makePartMatch()]} selectedMatches={new Set(["m1"])} actionLoading hasUnresolvedChecks={false} onToggleMatch={vi.fn()} onToggleAll={vi.fn()} onBatchReject={vi.fn()} onBatchApprove={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Processing..." })).toBeDisabled();
    expect(screen.getByTestId("stage2-desktop-match-region").querySelector("thead input[type='checkbox']")).toBeChecked();
    unmount();
  });
  it("ConsistencyChecksPanel renders empty state, rows, fallback, and resolve callback", () => {
    const onResolve = vi.fn();
    const checks = [makePartCheck(), makePartCheck({ id: "c2", check_type: "manual_review" as ConsistencyCheck["check_type"], severity: "low", details: { reason: "needs eyes" } })];
    const { rerender } = render(<ConsistencyChecksPanel checks={[]} onResolve={onResolve} />);
    expect(screen.getByText("No pending checks")).toBeInTheDocument();
    rerender(<ConsistencyChecksPanel checks={checks} onResolve={onResolve} />);
    expect(screen.getByText("2 total")).toBeInTheDocument();
    expect(screen.getByText("Potential duplicate")).toBeInTheDocument();
    expect(screen.getByText(JSON.stringify({ reason: "needs eyes" }))).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Resolve" })[0]);
    expect(onResolve).toHaveBeenCalledWith(checks[0]);
  });
  it("Stage2Filters fires change and toggle callbacks", () => {
    const onChange = vi.fn();
    const { rerender } = render(<Stage2Filters filters={{ checkType: "", status: "", severity: ["high"], minScore: 20 }} onChange={onChange} />);
    expect(screen.getByText("Min Match Score: 20")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "HIGH" }));
    expect(onChange).toHaveBeenCalledWith({ severity: [] });
    fireEvent.click(screen.getByRole("button", { name: "MEDIUM" }));
    expect(onChange).toHaveBeenCalledWith({ severity: ["high", "medium"] });
    const [checkTypeSelect, statusSelect] = screen.getAllByRole("combobox");
    fireEvent.change(checkTypeSelect, { target: { value: "anomaly" } });
    fireEvent.change(statusSelect, { target: { value: "resolved" } });
    fireEvent.change(screen.getByRole("slider"), { target: { value: "45" } });
    expect(onChange).toHaveBeenCalledWith({ checkType: "anomaly" });
    expect(onChange).toHaveBeenCalledWith({ status: "resolved" });
    expect(onChange).toHaveBeenCalledWith({ minScore: 45 });
    rerender(<Stage2Filters filters={{ checkType: "anomaly", status: "resolved", severity: [], minScore: 45 }} onChange={onChange} />);
  });
  it("RunSummaryPanel, ResolveCheckDialog, and label helpers cover all branches", () => {
    const onApproveRun = vi.fn(), onClose = vi.fn(), onResolve = vi.fn();
    const { rerender } = render(<RunSummaryPanel runId="run-1" unresolvedCounts={{ transfer: 1, duplicate: 1, anomaly: 1 }} processingPendingCount={0} pendingMatchesCount={3} actionLoading={false} approval={{ disabled: false, reason: "Approve" }} onApproveRun={onApproveRun} />);
    expect(screen.getByText("1 unresolved transfer")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve Run" }));
    expect(onApproveRun).toHaveBeenCalledTimes(1);
    rerender(<RunSummaryPanel runId="run-1" unresolvedCounts={{ transfer: 2, duplicate: 0, anomaly: 2 }} processingPendingCount={4} pendingMatchesCount={0} actionLoading approval={{ disabled: true, reason: "Resolve consistency checks first" }} onApproveRun={onApproveRun} />);
    expect(screen.getByText("2 unresolved transfers")).toBeInTheDocument();
    expect(screen.getByText("0 duplicates")).toBeInTheDocument();
    expect(screen.getByText("2 anomalies")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Processing..." })).toBeDisabled();
    const { rerender: rerenderDlg, unmount } = render(<ResolveCheckDialog check={makePartCheck({ details: {} })} actionLoading={false} onClose={onClose} onResolve={onResolve} />);
    const dialog = screen.getByRole("dialog", { name: "Resolve Consistency Check" });
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "note" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Flag" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Reject" }));
    expect(onResolve).toHaveBeenCalledWith("flag", "note");
    expect(onResolve).toHaveBeenCalledWith("reject", "note");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    fireEvent.click(document.querySelector(".fixed.inset-0[aria-hidden='true']") as HTMLElement);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(3);
    rerenderDlg(<ResolveCheckDialog check={makePartCheck()} actionLoading onClose={onClose} onResolve={onResolve} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(3);
    expect(checkSeverityColor("high")).toBe("text-[var(--error)]");
    expect(checkSeverityColor("medium")).toBe("text-[var(--warning)]");
    expect(checkSeverityColor("low")).toBe("text-muted");
    expect(checkTypeLabel("duplicate")).toBe("Duplicate");
    expect(checkTypeLabel("transfer_pair")).toBe("Transfer Pair");
    expect(checkTypeLabel("anomaly")).toBe("Anomaly");
    expect(checkTypeLabel("manual_review")).toBe("manual_review");
    unmount();
  });
}); // AC-reconciliation.fe-stage2-review.14 AC-reconciliation.fe-stage2-review.15 AC-reconciliation.fe-stage2-review.16 AC-reconciliation.fe-stage2-review.17 AC-reconciliation.fe-stage2-review.19 AC-reconciliation.fe-ia-reconciliation.9 AC-testing.fe-coverage.1

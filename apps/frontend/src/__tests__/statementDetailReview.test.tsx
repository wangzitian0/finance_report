import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";

import StatementReviewPage from "@/app/(main)/statements/[id]/page";
import { ToastProvider } from "@/components/ui/Toast";
import { ApiError } from "@/lib/api";
import { apiOperation } from "@/lib/api-client";
import { track, ANALYTICS_EVENTS } from "@/lib/analytics";

import { createInvalidationProbe } from "./fixtures/invalidationProbe";
import { renderReviewComponent } from "./helpers/renderReviewComponent";

const navigationState = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  searchParams: new URLSearchParams(),
}));
const pushMock = navigationState.push;
const replaceMock = navigationState.replace;

vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  apiOperation: vi.fn(),
  apiOperationDownload: vi.fn(() => Promise.resolve({ blob: new Blob(["%PDF"]), filename: "f.pdf" })),
}));
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ replace: replaceMock, push: pushMock })),
  useParams: vi.fn(() => ({ id: "s1" })),
  useSearchParams: vi.fn(() => navigationState.searchParams),
}));
vi.mock("@/lib/analytics", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/analytics")>()),
  track: vi.fn(),
}));

function mapOperationToLegacy(operationId: string, req: any = {}): [string, RequestInit | undefined] {
  switch (operationId) {
    case "get_statement_statements__statement_id__get":
    case "get_statement_for_review_statements__statement_id__review_get":
      return [`/api/statements/${req?.path?.statement_id ?? "s1"}/review`, undefined];
    case "list_pending_review_statements_pending_review_get":
      return ["/api/statements/pending-review", undefined];
    case "get_review_conflicts_review_conflicts__statement_id__get":
      return [`/api/review/conflicts/${req?.path?.statement_id ?? "s1"}`, undefined];
    case "list_accounts_accounts_get": {
      const q = req?.query;
      let path = "/api/accounts";
      if (q) {
        const params = new URLSearchParams();
        for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== null) params.append(k, String(v));
        const qs = params.toString();
        if (qs) path += `?${qs}`;
      }
      return [path, undefined];
    }
    case "create_account_accounts_post":
      return ["/api/accounts", { method: "POST", body: JSON.stringify(req?.body) }];
    case "approve_statement_stage1_statements__statement_id__review_approve_post":
      return [`/api/statements/${req?.path?.statement_id ?? "s1"}/review/approve`, { method: "POST", body: JSON.stringify(req?.body) }];
    case "edit_and_approve_statement_statements__statement_id__review_edit_post":
      return [`/api/statements/${req?.path?.statement_id ?? "s1"}/review/edit`, { method: "POST", body: JSON.stringify(req?.body) }];
    case "reject_statement_stage1_statements__statement_id__review_reject_post":
      return [`/api/statements/${req?.path?.statement_id ?? "s1"}/review/reject`, { method: "POST", body: JSON.stringify(req?.body) }];
    case "resolve_review_conflicts_review_conflicts__statement_id__resolve_post":
      return [`/api/review/conflicts/${req?.path?.statement_id ?? "s1"}/resolve`, { method: "POST", body: JSON.stringify(req?.body) }];
    case "retry_statement_parsing_statements__statement_id__retry_post":
      return [`/api/statements/${req?.path?.statement_id ?? "s1"}/retry`, { method: "POST" }];
    case "confirm_statement_review_envelope_statements__statement_id__review_envelope_post":
      return [`/api/statements/${req?.path?.statement_id ?? "s1"}/review/envelope`, { method: "POST", body: JSON.stringify(req?.body) }];
    case "create_correction_corrections_post":
      return ["/api/corrections", { method: "POST", body: JSON.stringify(req?.body) }];
    default:
      return [operationId, req];
  }
}

const mockedApi = vi.mocked(apiOperation);
const originalMockImplementation = mockedApi.mockImplementation.bind(mockedApi);
mockedApi.mockImplementation = (fn: any) =>
  originalMockImplementation((operationId: any, req: any) => {
    if (typeof operationId === "string" && operationId.startsWith("/")) return fn(operationId, req);
    const [path, options] = mapOperationToLegacy(operationId, req);
    return fn(path, options);
  });

const baseStatement = {
  id: "s1", original_filename: "statement.pdf", institution: "DBS", currency: "SGD",
  period_start: "2024-01-01", period_end: "2024-01-31", opening_balance: 100, closing_balance: 120,
  status: "parsed", stage1_status: null,
  balance_validation_result: {
    opening_balance: "100.00", closing_balance: "120.00", calculated_closing: "120.00",
    opening_delta: "0.00", closing_delta: "0.00", opening_match: true, closing_match: true, validated_at: "2024-01-31T00:00:00Z",
  },
  pdf_url: null,
  transactions: [
    { id: "txn-1", txn_date: "2024-01-03", description: "Salary", reference: "REF-1", amount: 20, direction: "IN", currency: "SGD", balance_after: 120, confidence: "high", status: "draft" },
  ],
};

const emptyConflicts = { duplicates: [], transfer_pairs: [] };

// AC-advisor.fe-chat.1
describe("AC16.1.2 AC16.1.3 Statement review page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigationState.searchParams = new URLSearchParams();
  });

  it("complete dormant source offers explicit human confirmation", async () => {
    // AC-extraction.human-source-review.4
    mockedApi.mockImplementation((path: string) => {
      if (path === "/api/statements/s1/review") {
        return Promise.resolve({
          ...baseStatement, account_id: "a1", confidence_score: 75, closing_balance: 100, transactions: [],
          source_result_digest: "a".repeat(64), source_missing_facts: [], source_envelope_reviewable: true, reviewed_envelope: null,
        });
      }
      if (path === "/api/accounts?account_type=ASSET&is_active=true") {
        return Promise.resolve({ items: [{ id: "a1", name: "Dormant Bank", type: "ASSET", currency: "SGD", is_active: true }], total: 1 });
      }
      if (path === "/api/statements/pending-review") return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
      if (path === "/api/review/conflicts/s1") return Promise.resolve(emptyConflicts);
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });
    renderReviewComponent(<StatementReviewPage /> as never);
    expect(await screen.findByText("Confirm source facts")).toBeInTheDocument();
    expect(screen.getByText(/needs your confirmation before it can be used/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Custody account")).toHaveValue("a1"));
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
  });

  // AC-extraction.fe-stage1-review.7
  it("AC16.18.4 shows loading feedback while review data is pending", async () => {
    let reviewAttempts = 0;
    mockedApi.mockImplementation((path: string) => {
      if (path === "/api/statements/s1/review") {
        reviewAttempts += 1;
        if (reviewAttempts === 1) return Promise.reject(new Error("network fail"));
        return Promise.resolve(baseStatement);
      }
      if (path === "/api/statements/pending-review") return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
      if (path === "/api/review/conflicts/s1") return Promise.resolve(emptyConflicts);
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });

    renderReviewComponent(<StatementReviewPage /> as never);
    expect(screen.getByRole("status", { name: "Loading statement" })).toBeInTheDocument();
    expect(await screen.findByText("Failed to load statement")).toBeInTheDocument();
    expect(screen.getByText("network fail")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("statement.pdf")).toBeInTheDocument();
    // The failed statement read, the retried statement read, then the review read.
    expect(reviewAttempts).toBe(3);
  });

  // AC-extraction.fe-stage1-review.8
  it("AC16.18.5 disables approve when balance validation fails", async () => {
    const retryResolved = vi.fn();
    mockedApi.mockImplementation((path: string, init?: any) => {
      if (path === "/api/statements/s1/review") {
        return Promise.resolve({
          ...baseStatement,
          balance_validation_result: { ...baseStatement.balance_validation_result, closing_match: false },
        });
      }
      if (path === "/api/statements/pending-review") return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
      if (path === "/api/review/conflicts/s1") return Promise.resolve(emptyConflicts);
      if (path === "/api/statements/s1/retry") {
        retryResolved(init?.method);
        return Promise.resolve({});
      }
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });

    renderReviewComponent(<StatementReviewPage /> as never);
    expect(await screen.findByRole("button", { name: "Approve" })).toBeDisabled();
    // AC22.5.2
    fireEvent.click(screen.getByRole("button", { name: /Re-parse statement/i }));
    await waitFor(() => expect(retryResolved).toHaveBeenCalledWith("POST"));
  });

  // AC-extraction.fe-stage1-review.13
  it("AC16.31.2 disables approval when opening balance validation fails", async () => {
    mockedApi.mockImplementation((path: string) => {
      if (path === "/api/statements/s1/review") {
        return Promise.resolve({
          ...baseStatement,
          balance_validation_result: { ...baseStatement.balance_validation_result, opening_match: false, closing_match: true },
        });
      }
      if (path === "/api/statements/pending-review") return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
      if (path === "/api/review/conflicts/s1") return Promise.resolve(emptyConflicts);
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });

    renderReviewComponent(<StatementReviewPage /> as never);
    expect(await screen.findByRole("button", { name: "Approve" })).toBeDisabled();
  });

  // AC-extraction.fe-stage1-review.14
  it("AC16.32.2 shows opening and closing balance validation states separately", async () => {
    mockedApi.mockImplementation((path: string) => {
      if (path === "/api/statements/s1/review") {
        return Promise.resolve({
          ...baseStatement,
          balance_validation_result: {
            ...baseStatement.balance_validation_result,
            opening_match: false, closing_match: true, opening_delta: "5.00", closing_delta: "0.00",
          },
        });
      }
      if (path === "/api/statements/pending-review") return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
      if (path === "/api/review/conflicts/s1") return Promise.resolve(emptyConflicts);
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });

    renderReviewComponent(<StatementReviewPage /> as never);
    expect(await screen.findByText("Opening Mismatch")).toBeInTheDocument();
    expect(screen.getByText("Closing Valid")).toBeInTheDocument();
    expect(screen.getByText("Opening Δ: 5.00")).toBeInTheDocument();
    expect(screen.getByText("Closing Δ: 0.00")).toBeInTheDocument();
  });

  it("AC-extraction.reviewed-envelope.6 confirms missing source envelope facts before approval", async () => {
    let confirmed = false;
    // The mocked POST resolves this promise: the test waits for the request, not for a time (#2648 CI).
    let markPosted: () => void = () => undefined;
    const posted = new Promise<void>((resolve) => {
      markPosted = resolve;
    });
    mockedApi.mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/statements/s1/review") {
        if (confirmed) {
          return Promise.resolve({
            ...baseStatement, account_id: "a1", source_result_digest: "a".repeat(64),
            source_missing_facts: ["statement_currency", "period", "balances"],
            reviewed_envelope: {
              id: "review-1", source_result_digest: "a".repeat(64), account_id: "a1", currency: "SGD",
              period_start: "2024-01-01", period_end: "2024-01-31", opening_balance: "100.00", closing_balance: "120.00",
              rationale: "The CSV has no statement header.", review_trace_record_id: "trace-1", created_at: "2024-02-01T00:00:00Z",
            },
          });
        }
        return Promise.resolve({
          ...baseStatement, account_id: null, currency: null, period_start: null, opening_balance: null, closing_balance: null,
          source_result_digest: "a".repeat(64), source_missing_facts: ["statement_currency", "period", "balances"],
          source_envelope_reviewable: true, reviewed_envelope: null,
        });
      }
      if (path === "/api/accounts?account_type=ASSET&is_active=true") {
        return Promise.resolve({ items: [{ id: "a1", name: "DBS Cash", type: "ASSET", currency: "SGD", is_active: true }], total: 1 });
      }
      if (path === "/api/statements/pending-review") return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
      if (path === "/api/review/conflicts/s1") return Promise.resolve(emptyConflicts);
      if (path === "/api/statements/s1/review/envelope") {
        expect(options).toMatchObject({ method: "POST" });
        confirmed = true;
        markPosted();
        return Promise.resolve({ id: "review-1" });
      }
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });

    const probe = createInvalidationProbe("statements.review.confirm-envelope", ["s1"]);
    const ProbeWrapperComponent = probe.wrapper;
    const ProbeWrapper = ({ children }: { children: ReactNode }) => (
      <ProbeWrapperComponent><ToastProvider>{children}</ToastProvider></ProbeWrapperComponent>
    );
    render(<StatementReviewPage /> as never, { wrapper: ProbeWrapper });

    expect(await screen.findByText("Confirm missing source facts")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();

    // The custody accounts load after the review. A change before the option exists keeps the
    // select empty, the form stays incomplete and the click sends no request (the CI failure).
    await within(screen.getByLabelText("Custody account")).findByRole("option", { name: "DBS Cash (SGD)" });
    fireEvent.change(screen.getByLabelText("Custody account"), { target: { value: "a1" } });
    fireEvent.change(screen.getByLabelText("Statement currency"), { target: { value: "SGD" } });
    fireEvent.change(screen.getByLabelText("Period start"), { target: { value: "2024-01-01" } });
    fireEvent.change(screen.getByLabelText("Period end"), { target: { value: "2024-01-31" } });
    fireEvent.change(screen.getByLabelText("Opening balance"), { target: { value: "100" } });
    fireEvent.change(screen.getByLabelText("Closing balance"), { target: { value: "120" } });
    fireEvent.change(screen.getByLabelText("Why are these facts confirmed?"), { target: { value: "The CSV has no statement header." } });
    const confirm = screen.getByRole("button", { name: "Confirm source envelope" });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);

    await posted;
    expect(mockedApi).toHaveBeenCalledWith("confirm_statement_review_envelope_statements__statement_id__review_envelope_post", expect.objectContaining({ path: { statement_id: "s1" } }));
    await waitFor(() => probe.expectDeclaredInvalidated());
    await waitFor(() => expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled());
  });

  it("AC-extraction.reviewed-envelope.6 does not offer a cash envelope for unsupported source facts", async () => {
    mockedApi.mockImplementation((path: string) => {
      if (path === "/api/statements/s1/review") {
        return Promise.resolve({
          ...baseStatement, source_result_digest: "a".repeat(64), source_missing_facts: ["transaction_currency"],
          source_envelope_reviewable: false, reviewed_envelope: null,
        });
      }
      if (path === "/api/statements/pending-review") return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
      if (path === "/api/review/conflicts/s1") return Promise.resolve(emptyConflicts);
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });

    renderReviewComponent(<StatementReviewPage /> as never);
    expect(await screen.findByText("Source review required")).toBeInTheDocument();
    expect(screen.getByText(/transaction currency cannot be confirmed by a cash statement envelope/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm source envelope" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
  });

  it("AC-extraction.2477.1 creates an inline asset account in the statement currency and selects it", async () => {
    let created = false;
    const createdAccount = { id: "acc-1", name: "DBS account", currency: "SGD" };
    mockedApi.mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/statements/s1/review") {
        return Promise.resolve({
          ...baseStatement, account_id: null, source_envelope_reviewable: true,
          source_missing_facts: [], source_result_digest: "digest-1", reviewed_envelope: null,
        });
      }
      if (path.startsWith("/api/accounts")) {
        if (options?.method === "POST") {
          created = true;
          return Promise.resolve(createdAccount);
        }
        return Promise.resolve({ items: created ? [createdAccount] : [] });
      }
      if (path === "/api/statements/pending-review") return Promise.resolve({ items: [{ id: "s1" }] });
      if (path === "/api/review/conflicts/s1") return Promise.resolve(emptyConflicts);
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });

    renderReviewComponent(<StatementReviewPage /> as never);
    const button = await screen.findByRole("button", { name: "Create account" });
    await act(async () => {});
    fireEvent.click(button);

    expect(await screen.findByText('Account "DBS account" created and selected.')).toBeInTheDocument();
    await waitFor(() => expect((document.getElementById("custody-account") as HTMLSelectElement).value).toBe("acc-1"));
  });

  // AC-extraction.fe-stage1-review.9
  it("AC16.18.6 approves and rejects in place on the statement page without leaving it", async () => {
    let status = "parsed";
    mockedApi.mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/statements/s1/review") return Promise.resolve({ ...baseStatement, status, validation_error: status === "rejected" ? "Rejected by reviewer" : null });
      if (path === "/api/statements/pending-review") return Promise.resolve({ items: [{ id: "s0" }, { id: "s1" }, { id: "s2" }], total: 3 });
      if (path === "/api/review/conflicts/s1") return Promise.resolve(emptyConflicts);
      if (path === "/api/statements/s1/review/approve") {
        status = "approved";
        return Promise.resolve({ journal_entries_created: 2 });
      }
      if (path === "/api/statements/s1/review/reject") {
        expect(options).toMatchObject({ method: "POST", body: JSON.stringify({ notes: "Needs re-parse" }) });
        status = "rejected";
        return Promise.resolve({ success: true });
      }
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });

    renderReviewComponent(<StatementReviewPage /> as never);

    fireEvent.click(await screen.findByRole("button", { name: "← Prev" }));
    fireEvent.click(screen.getByRole("button", { name: "Next →" }));
    expect(pushMock).toHaveBeenNthCalledWith(1, "/statements/s0");
    expect(pushMock).toHaveBeenNthCalledWith(2, "/statements/s2");

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    const approveDialog = await screen.findByRole("dialog", { name: "Approve Statement" });
    fireEvent.click(within(approveDialog).getByRole("button", { name: "Approve" }));

    expect(await screen.findByText("Statement approved. 2 journal entries created.")).toBeInTheDocument();
    // AC22.18.3
    expect(vi.mocked(track)).toHaveBeenCalledWith(ANALYTICS_EVENTS.REVIEW_APPROVED, expect.objectContaining({ statement_id: "s1" }));
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(pushMock).toHaveBeenCalledTimes(2);
  });

  it("AC16.18.6 rejects with a reason and shows the failed-parse recovery on the same page", async () => {
    let status = "parsed";
    mockedApi.mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/statements/s1/review") return Promise.resolve({ ...baseStatement, status, validation_error: status === "rejected" ? "Rejected by reviewer" : null });
      if (path === "/api/statements/pending-review") return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
      if (path === "/api/review/conflicts/s1") return Promise.resolve(emptyConflicts);
      if (path === "/api/statements/s1/review/reject") {
        expect(options).toMatchObject({ method: "POST", body: JSON.stringify({ notes: "Needs re-parse" }) });
        status = "rejected";
        return Promise.resolve({ success: true });
      }
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });

    renderReviewComponent(<StatementReviewPage /> as never);
    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
    const rejectDialog = await screen.findByRole("dialog", { name: "Reject Statement" });
    fireEvent.change(within(rejectDialog).getByRole("textbox"), { target: { value: "Needs re-parse" } });
    fireEvent.click(within(rejectDialog).getByRole("button", { name: "Reject" }));

    expect(await screen.findByText("Parsing Failed")).toBeInTheDocument();
    expect(screen.getByText("Rejected by reviewer")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry Parse" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(pushMock).not.toHaveBeenCalled();
  });

  // AC-extraction.fe-stage1-review.17
  it("AC-extraction.fe-stage1-review.17 supports auto_fill_default_categories via auto-fill action on classification review", async () => {
    let capturedBody: { auto_fill_default_categories?: boolean } | null = null;
    mockedApi.mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/statements/s1/review") {
        return Promise.resolve({ ...baseStatement, validation_error: "Economic review required: intent_missing" });
      }
      if (path === "/api/statements/pending-review") return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
      if (path === "/api/review/conflicts/s1") return Promise.resolve(emptyConflicts);
      if (path === "/api/statements/s1/review/approve") {
        capturedBody = JSON.parse(options?.body as string);
        return Promise.resolve({ journal_entries_created: 2 });
      }
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });

    renderReviewComponent(<StatementReviewPage /> as never);
    fireEvent.click(await screen.findByRole("button", { name: "Auto-Fill Default Categories & Approve" }));
    await waitFor(() => expect(capturedBody).toMatchObject({ auto_fill_default_categories: true }));
  });

  it("AC-extraction.fe-ia-extraction.4 routes economic-review conflicts to the exact statement queue", async () => {
    // AC-extraction.disposition.5
    let economicReviewRequired = false;
    mockedApi.mockImplementation((path: string) => {
      if (path === "/api/statements/s1/review") {
        return Promise.resolve({
          ...baseStatement,
          validation_error: economicReviewRequired ? "Economic review required: intent_missing" : null,
        });
      }
      if (path === "/api/statements/pending-review") return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
      if (path === "/api/review/conflicts/s1") return Promise.resolve(emptyConflicts);
      if (path === "/api/statements/s1/review/approve") {
        economicReviewRequired = true;
        return Promise.reject(new ApiError("Economic review required: intent_missing", 409));
      }
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });

    renderReviewComponent(<StatementReviewPage /> as never);
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    fireEvent.click(within(await screen.findByRole("dialog", { name: "Approve Statement" })).getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(screen.getByText("Economic classification needs review before entries can be posted.")).toBeInTheDocument());
    expect(await screen.findByRole("link", { name: "Review transaction classifications" })).toHaveAttribute(
      "href",
      "/reconciliation?tab=unmatched&statement_id=s1&return_to=%2Fstatements%2Fs1",
    );
    expect(screen.getByRole("link", { name: "Review AI suggestions" })).toHaveAttribute(
      "href",
      "/audit?tab=needs-you&statement_id=s1&return_to=%2Fstatements%2Fs1#ai-suggestions",
    );
  });

  // AC-reconciliation.fe-stage2-review.18 / AC-reconciliation.fe-stage2-review.23
  it("AC16.23.3 AC16.31.1 opens the conflict dialog when duplicate or transfer-pair candidates exist", async () => {
    // AC16.32.1 / AC16.34.3 / AC-testing.fe-async.2
    const duplicate = { id: "t1", txn_date: "2025-01-15", description: "Duplicate deposit", amount: "20.00", direction: "IN" };
    const transfer = { id: "t2", txn_date: "2025-01-16", description: "Transfer to savings", amount: "20.00", direction: "OUT" };
    mockedApi.mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/statements/s1/review") return Promise.resolve(baseStatement);
      if (path === "/api/statements/pending-review") return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
      if (path === "/api/review/conflicts/s1") return Promise.resolve({ duplicates: [duplicate], transfer_pairs: [transfer] });
      if (path === "/api/review/conflicts/s1/resolve" && options?.method === "POST") {
        expect(JSON.parse(options?.body as string)).toEqual({ action: "confirm_distinct" });
        return Promise.resolve({ resolved: true, resolved_at: "2026-06-14T00:00:00Z" });
      }
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });

    const probe = createInvalidationProbe("statements.review.resolve-conflicts", ["s1"]);
    const ProbeWrapperComponent = probe.wrapper;
    const ProbeWrapper = ({ children }: { children: ReactNode }) => (
      <ProbeWrapperComponent><ToastProvider>{children}</ToastProvider></ProbeWrapperComponent>
    );
    render(<StatementReviewPage /> as never, { wrapper: ProbeWrapper });

    const approveButton = await screen.findByRole("button", { name: "Approve" });
    expect(approveButton).toBeDisabled();
    expect(screen.getByText(/Approve is paused/i)).toBeInTheDocument();

    const dialog = await screen.findByRole("dialog", { name: "Resolve Conflicts" });
    expect(within(dialog).getByText("Duplicate Candidates")).toBeInTheDocument();
    expect(within(dialog).getByText("Transfer Pair Candidates")).toBeInTheDocument();

    probe.expectNothingInvalidated();
    fireEvent.click(within(dialog).getByRole("button", { name: "Resolve" }));

    await waitFor(() => expect(mockedApi).toHaveBeenCalledWith("resolve_review_conflicts_review_conflicts__statement_id__resolve_post", expect.objectContaining({ path: { statement_id: "s1" } })));
    await waitFor(() => probe.expectDeclaredInvalidated());
  });

  it("AC22.11.3 returns attention-origin statement review actions to the attention queue", async () => {
    navigationState.searchParams = new URLSearchParams("from=attention");
    mockedApi.mockImplementation((path: string) => {
      if (path === "/api/statements/s1/review") return Promise.resolve(baseStatement);
      if (path === "/api/statements/pending-review") return Promise.resolve({ items: [{ id: "s0" }, { id: "s1" }, { id: "s2" }], total: 3 });
      if (path === "/api/review/conflicts/s1") return Promise.resolve(emptyConflicts);
      if (path === "/api/statements/s1/review/approve") return Promise.resolve({ journal_entries_created: 1 });
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });

    renderReviewComponent(<StatementReviewPage /> as never);
    expect(await screen.findByRole("link", { name: /Back to Needs Confirmation/i })).toHaveAttribute("href", "/audit?tab=needs-you");

    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    const dialog = await screen.findByRole("dialog", { name: "Approve Statement" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(pushMock).toHaveBeenLastCalledWith("/audit?tab=needs-you"));
  });

  // AC-extraction.fe-stage1-review.7
  it("opens LowConfidenceReviewModal, saves category correction, and routes Ask AI Assistant to /chat", async () => {
    let currentCategory: string | null = null;
    mockedApi.mockImplementation((path: any, options?: any) => {
      if (path === "/api/statements/s1/review") {
        return Promise.resolve({
          ...baseStatement,
          transactions: [{ ...baseStatement.transactions[0], proposed_category: currentCategory, confidence_tier: currentCategory ? "HIGH" : "LOW" }],
        });
      }
      if (path === "/api/statements/pending-review") return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
      if (path === "/api/review/conflicts/s1") return Promise.resolve(emptyConflicts);
      if (path === "/api/corrections") {
        const body = JSON.parse(String(options?.body));
        currentCategory = body.corrected_category;
        return Promise.resolve({ id: "corr-1", transaction_id: body.transaction_id, corrected_category: body.corrected_category });
      }
      if (path === "/api/statements/s1/review/approve") return Promise.resolve({ journal_entries_created: 1 });
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });

    renderReviewComponent(<StatementReviewPage /> as never);
    const reviewBtns = await screen.findAllByRole("button", { name: "Review" });
    fireEvent.click(reviewBtns[0]);
    expect(await screen.findByText("Review Low-Confidence Transaction")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ask AI Assistant" }));
    expect(pushMock).toHaveBeenCalledWith("/chat");
    fireEvent.click(screen.getByRole("button", { name: "Salary" }));
    fireEvent.click(screen.getByRole("button", { name: /save correction/i }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(mockedApi).toHaveBeenCalledWith("create_correction_corrections_post", expect.objectContaining({ body: { transaction_id: "txn-1", corrected_category: "SALARY" } }));
  });

  // AC-extraction.fe-stage1-review.25
  it("AC-extraction.fe-stage1-review.25 shows the preview panel for a PDF source and none for a CSV source", async () => {
    for (const [filename, filePath, hasPreview] of [
      ["statement.pdf", "statements/statement.pdf", true],
      ["october.csv", "statements/october.csv", false],
      ["OCTOBER.CSV", "statements/OCTOBER.CSV", false],
    ] as const) {
      mockedApi.mockImplementation((path: string) => {
        if (path === "/api/statements/s1/review") return Promise.resolve({ ...baseStatement, original_filename: filename, file_path: filePath });
        if (path === "/api/statements/pending-review") return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
        if (path === "/api/review/conflicts/s1") return Promise.resolve(emptyConflicts);
        return Promise.reject(new Error(`Unexpected path ${path}`));
      });
      const view = renderReviewComponent(<StatementReviewPage /> as never);
      const workbench = await screen.findByTestId("statement-side-by-side-workbench");
      expect(await within(workbench).findAllByText("Salary")).not.toHaveLength(0);
      expect(within(workbench).queryAllByRole("heading", { name: "PDF Preview" }), filename).toHaveLength(hasPreview ? 1 : 0);
      // Without a preview the table takes the full desktop width and has no fixed height.
      const tableColumn = within(workbench).getByTestId("stage1-desktop-transaction-region").closest(".order-1");
      expect(tableColumn, filename).toHaveClass(hasPreview ? "lg:col-span-7" : "lg:col-span-12");
      expect(tableColumn?.className.includes("lg:h-[600px]"), filename).toBe(hasPreview);
      view.unmount();
    }
  });

  // AC-extraction.fe-stage1-review.28
  it("AC-extraction.fe-stage1-review.28 hides Import to Portfolio on bank statements and collapses unavailable PDF preview", async () => {
    mockedApi.mockImplementation((path: string) => {
      if (path === "/api/statements/s1/review") {
        return Promise.resolve({
          ...baseStatement,
          original_filename: "bsb_001_straits_capital.pdf",
          institution: "Straits Capital",
          file_path: "",
          status: "approved",
          transactions: [{ ...baseStatement.transactions[0], status: "pending" }],
        });
      }
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });

    const { StatementHeader } = await import("@/components/review/StatementReview");
    const { statementDisplayTitle, canImportBrokerageStatement } = await import("@/lib/statusLabels");
    expect(statementDisplayTitle({ original_filename: "", institution: "DBS", period_start: "2026-01-01", period_end: "2026-01-31" })).toBe("DBS (2026-01-01 – 2026-01-31)");
    expect(canImportBrokerageStatement({ institution: "Straits Capital", original_filename: "bsb_001_straits_capital.pdf", brokerage_import_failed: false })).toBe(false);
    expect(canImportBrokerageStatement({ institution: "Interactive Brokers", original_filename: "ibkr.pdf", brokerage_import_failed: false })).toBe(true);
    void StatementHeader;

    renderReviewComponent(<StatementReviewPage /> as never);
    const workbench = await screen.findByTestId("statement-side-by-side-workbench");
    expect(await within(workbench).findAllByText("Salary")).not.toHaveLength(0);
    expect(screen.queryByRole("button", { name: /import brokerage positions to portfolio/i })).toBeNull();
    expect(screen.queryByText("pending")).toBeNull();
    const previewWrapper = within(workbench).getByRole("heading", { name: "PDF Preview" }).closest(".order-2");
    expect(previewWrapper).not.toHaveClass("h-[480px]");
  });
});

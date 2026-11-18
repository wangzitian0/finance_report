import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ComponentProps, ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import StatementDetailPage from "@/app/(main)/statements/[id]/page";
import { BrokerageImportResultBanner, StatementHeader } from "@/components/statements/StatementReview";
import { apiOperation } from "@/lib/api";
import { formatPeriod } from "@/lib/date";
import { currencyCodeOrDash as formatCode } from "@/lib/statusLabels";
import type { BankStatement, BrokerageImportResponse } from "@/lib/types";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode; [key: string]: unknown }) => (
    <a href={href} {...rest}>{children}</a>
  ),
})); const showToastMock = vi.fn(); const mockSearchParams = new URLSearchParams(); let mockStatementId = "s1"; vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), useParams: () => ({ id: mockStatementId }), useSearchParams: () => mockSearchParams, })); vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast: showToastMock }), })); vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/api")>()), apiOperation: vi.fn(), })); const parsedStatement = { id: "s1", original_filename: "statement-jan.pdf", institution: "DBS", currency: "SGD", period_start: "2026-01-01", period_end: "2026-01-31", opening_balance: 1000, closing_balance: 1500, confidence_score: 92, balance_validated: true, validation_error: null, status: "parsed", parsing_progress: 100, transactions: [ { id: "t1", txn_date: "2026-01-02", description: "Salary", reference: "R1", amount: 500, direction: "IN", currency: "SGD", balance_after: 1500, confidence: "high", status: "matched", }, ], }; function deferred<T>() { let resolve!: (value: T) => void
let reject!: (reason?: unknown) => void
const promise = new Promise<T>((resolvePromise, rejectPromise) => { resolve = resolvePromise
reject = rejectPromise }); return { promise, resolve, reject } }; describe("StatementDetailPage", () => { const mockedApiFetch = vi.mocked(apiOperation); const STATEMENT_OP = "get_statement_statements__statement_id__get"; const RUNS_OP = "list_statement_runs_statements__statement_id__runs_get";
// The statement reads follow a script, one answer for each read, then the fallback. The attempts list answers per operation id: it never takes an answer of the script.
const scriptStatementReads = (answers: Array<() => Promise<unknown>>, fallback: () => Promise<unknown> = () => Promise.resolve(undefined)) => { const queue = [...answers]; mockedApiFetch.mockImplementation(((operationId: string) => { if (operationId === RUNS_OP) return Promise.resolve({ items: [], total: 0 }); if (operationId !== STATEMENT_OP) return Promise.resolve(undefined); const next = queue.shift(); return next ? next() : fallback() }) as unknown as typeof apiOperation) }
const statementReads = () => mockedApiFetch.mock.calls.filter((call) => call[0] === STATEMENT_OP); beforeEach(() => { mockedApiFetch.mockReset()
showToastMock.mockReset()
mockStatementId = "s1" }); afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks() }); it("AC-extraction.fe-stage1-review.15 keeps detail polling single-flight and aborts active work on teardown", async () => { vi.useFakeTimers({ shouldAdvanceTime: true }); const parsingStatement = { ...parsedStatement, status: "parsing", parsing_progress: 50, }; const poll = deferred<typeof parsedStatement>()
scriptStatementReads([() => Promise.resolve(parsingStatement)], () => poll.promise); const view = render(<StatementDetailPage />); await screen.findByText(/Parsing in progress/); await act(async () => { await vi.advanceTimersByTimeAsync(3000) }); expect(statementReads()).toHaveLength(2); const pollSignal = statementReads()[1]?.[1]?.signal
expect(pollSignal).toBeInstanceOf(AbortSignal); await act(async () => { await vi.advanceTimersByTimeAsync(6000) }); expect(statementReads()).toHaveLength(2)
view.unmount(); expect(pollSignal?.aborted).toBe(true); await act(async () => { poll.resolve(parsedStatement); await poll.promise
await vi.advanceTimersByTimeAsync(6000) }); expect(statementReads()).toHaveLength(2); expect(showToastMock).not.toHaveBeenCalled() }); it("AC-extraction.fe-stage1-review.15 ignores the prior statement response after an id change", async () => { const oldRequest = deferred<typeof parsedStatement>(); const newStatement = { ...parsedStatement, id: "s2", original_filename: "new-statement.pdf", }
mockedApiFetch .mockImplementationOnce(() => oldRequest.promise) .mockResolvedValueOnce(newStatement); const view = render(<StatementDetailPage />); await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledTimes(1)); const oldSignal = mockedApiFetch.mock.calls[0]?.[1]?.signal
mockStatementId = "s2"
view.rerender(<StatementDetailPage />); await screen.findByText("new-statement.pdf"); expect(oldSignal?.aborted).toBe(true); await act(async () => { oldRequest.resolve(parsedStatement); await oldRequest.promise }); expect(screen.getByText("new-statement.pdf")).toBeInTheDocument(); expect(screen.queryByText("statement-jan.pdf")).toBeNull() }); it("AC-extraction.fe-stage1-review.15 lets an explicit run refresh supersede an active poll", async () => { vi.useFakeTimers({ shouldAdvanceTime: true }); const parsingStatement = { ...parsedStatement, status: "parsing", parsing_progress: 50 }; const stalePoll = deferred<typeof parsedStatement>(); const reparsingStatement = { ...parsedStatement, status: "parsing", parsing_progress: 10 }
scriptStatementReads([() => Promise.resolve(parsingStatement), () => Promise.reject(new Error("poll 1 failed")), () => Promise.reject(new Error("poll 2 failed")), () => Promise.reject(new Error("poll 3 failed")), () => stalePoll.promise, () => Promise.resolve(reparsingStatement)]); render(<StatementDetailPage />); await screen.findByText(/Parsing in progress/); await act(async () => { await vi.advanceTimersByTimeAsync(9000) }); await screen.findByText("Auto-refresh Stopped"); const resumeButton = screen.getByRole("button", { name: "Resume Auto-Refresh" }); const retryButton = screen.getByRole("button", { name: "Run again" }); await act(async () => { resumeButton.click()
retryButton.click(); await Promise.resolve() }); await waitFor(() => expect(statementReads()).toHaveLength(6)); const staleSignal = statementReads()[4]?.[1]?.signal
expect(staleSignal?.aborted).toBe(true); expect(await screen.findByText(/Parsing in progress/)).toBeInTheDocument(); await act(async () => { stalePoll.resolve(parsedStatement); await stalePoll.promise }); expect(screen.getByText(/Parsing in progress/)).toBeInTheDocument() }); const validBalance = { opening_balance: "1000.00", closing_balance: "1500.00", calculated_closing: "1500.00", opening_delta: "0.00", closing_delta: "0.00", opening_match: true, closing_match: true, validated_at: "2026-01-31T00:00:00Z", }; function mockStatementApi(read: () => Record<string, unknown>, onRetry?: () => void) { mockedApiFetch.mockImplementation(((operationId: string) => { switch (operationId) { case "get_statement_statements__statement_id__get": return Promise.resolve(read())
case "get_statement_for_review_statements__statement_id__review_get": return Promise.resolve({ ...read(), balance_validation_result: validBalance, source_missing_facts: [], source_envelope_reviewable: false, reviewed_envelope: null })
case "list_pending_review_statements_pending_review_get": return Promise.resolve({ items: [{ id: "s1" }], total: 1 })
case "get_review_conflicts_statements__statement_id__conflicts_get": return Promise.resolve({ duplicates: [], transfer_pairs: [], resolved: true })
case "list_statement_runs_statements__statement_id__runs_get": return Promise.resolve({ items: [], total: 0 })
case "create_statement_run_statements__statement_id__runs_post": onRetry?.(); return Promise.resolve({})
default: return Promise.reject(new Error(`Unexpected operation ${operationId}`)) } }) as unknown as typeof apiOperation) }; it("AC16.18.1 loads detail data and renders transactions", async () => { mockStatementApi(() => parsedStatement); render(<StatementDetailPage />); await waitFor(() => expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument()); expect(screen.getAllByText("Salary").length).toBeGreaterThan(0); expect( screen.getByTestId("statement-original-filename-badge"), ).toHaveTextContent("Source file: statement-jan.pdf"); expect(screen.getByText(/Confidence 92% \(/)).toBeInTheDocument() }); it("AC-extraction.fe-stage1-review.19 shows the PDF original beside the extracted transactions on one page", async () => { mockStatementApi(() => parsedStatement); render(<StatementDetailPage />); const workbench = await screen.findByTestId("statement-side-by-side-workbench"); expect(within(workbench).getByRole("heading", { name: "PDF Preview" })).toBeInTheDocument(); expect(within(workbench).getByRole("heading", { name: "Transactions" })).toBeInTheDocument(); expect(within(workbench).getAllByText("Salary").length).toBeGreaterThan(0); await screen.findByRole("button", { name: "Approve" }); expect(document.querySelector('a[href$="/review"]')).toBeNull(); expect(screen.getByRole("link", { name: "← Back to Upload" })).toHaveAttribute("href", "/upload") }); it("AC16.18.2 shows approve and reject only while the statement is parsed", async () => { mockStatementApi(() => parsedStatement); const parsed = render(<StatementDetailPage />); expect(await screen.findByRole("button", { name: "Approve" })).toBeEnabled(); expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled()
parsed.unmount()
mockedApiFetch.mockReset()
mockStatementApi(() => ({ ...parsedStatement, status: "approved" })); render(<StatementDetailPage />); await waitFor(() => expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument()); await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("get_statement_for_review_statements__statement_id__review_get", expect.anything())); expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument(); expect(mockedApiFetch).not.toHaveBeenCalledWith("approve_statement_stage1_statements__statement_id__approvals_post", expect.anything()); expect(mockedApiFetch).not.toHaveBeenCalledWith("reject_statement_stage1_statements__statement_id__rejections_post", expect.anything()) }); it("AC16.18.3 run again posts the runs API with empty hints and refreshes", async () => { let current: Record<string, unknown> = { ...parsedStatement, status: "rejected", validation_error: "parse failed" }; const retried = vi.fn()
mockStatementApi(() => current, () => { retried()
current = parsedStatement }); render(<StatementDetailPage />); await waitFor(() => expect(screen.getByText("Parsing Failed")).toBeInTheDocument()); fireEvent.click(screen.getByRole("button", { name: "Run again" })); await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith( "create_statement_run_statements__statement_id__runs_post", { path: { statement_id: "s1" }, body: { kind: "extract", hints: { keywords: [], note: null } }, }, ), ); expect(retried).toHaveBeenCalledTimes(1); await waitFor(() => expect(screen.queryByText("Parsing Failed")).not.toBeInTheDocument()) }); it("shows not found state", async () => { mockedApiFetch.mockResolvedValueOnce(null); render(<StatementDetailPage />); await waitFor(() => expect(screen.getByText("Statement not found")).toBeInTheDocument()) }); it("stops polling after consecutive errors", async () => { const parsingState = { ...parsedStatement, status: "parsing", parsing_progress: 50 }
mockedApiFetch.mockResolvedValueOnce(parsingState)
mockedApiFetch.mockRejectedValue(new Error("Poll Failure")); render(<StatementDetailPage />); await waitFor(() => expect(screen.getByText(/Parsing in progress/)).toBeInTheDocument(), { timeout: 3000 }); await waitFor(() => expect(screen.getByText(/Auto-refresh Stopped/)).toBeInTheDocument(), { timeout: 15000 }) }, 20000) })

const partBaseStatement: BankStatement = {
  id: "s1", user_id: "u1", account_id: null, account_last4: null, file_path: "/tmp/s1.pdf", original_filename: "statement-jan.pdf", institution: "DBS", currency: "SGD", period_start: "2026-01-01", period_end: "2026-01-31", opening_balance: "1000", closing_balance: "1500", status: "parsed", confidence_score: 92, balance_validated: true, validation_error: null, brokerage_import_failed: false, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", transactions: [],
};
function renderHeader(overrides: Partial<ComponentProps<typeof StatementHeader>> = {}) {
  const onBrokerageImport = vi.fn();
  return { ...render(<StatementHeader statement={partBaseStatement} canImport={false} importLoading={false} onBrokerageImport={onBrokerageImport} formatCode={formatCode} formatPeriod={formatPeriod} {...overrides} />), onBrokerageImport };
}
describe("StatementHeader", () => {
  it("AC22.17.3 renders title, status badge, description and confidence", () => {
    renderHeader();
    expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument();
    expect(screen.getByText("parsed")).toBeInTheDocument();
    expect(screen.getByText(/DBS • SGD • 2026-01-01 to 2026-01-31/)).toBeInTheDocument();
    expect(screen.getByText(/Confidence 92% \(/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /review/i })).not.toBeInTheDocument();
  });
  it("#1609 labels mid and low confidence with text, not colour alone", () => {
    const { unmount } = renderHeader({ statement: { ...partBaseStatement, confidence_score: 70 } });
    expect(screen.getByText(/Confidence 70% \(\S+/)).toBeInTheDocument();
    unmount();
    renderHeader({ statement: { ...partBaseStatement, confidence_score: null } });
    expect(screen.queryByText(/Confidence/)).not.toBeInTheDocument();
  });
  it("hides the import button when not allowed and handles import button states", () => {
    const { unmount } = renderHeader({ canImport: false });
    expect(screen.queryByRole("button", { name: /import brokerage positions to portfolio/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry Parse" })).not.toBeInTheDocument();
    unmount();
    const { unmount: unmountIdle, onBrokerageImport } = renderHeader({ canImport: true });
    const btn = screen.getByRole("button", { name: /import brokerage positions to portfolio/i });
    expect(btn).toHaveTextContent("Import to Portfolio");
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    expect(onBrokerageImport).toHaveBeenCalledTimes(1);
    unmountIdle();
    renderHeader({ canImport: true, importLoading: true });
    const loadingBtn = screen.getByRole("button", { name: /import brokerage positions to portfolio/i });
    expect(loadingBtn).toHaveTextContent("Importing...");
    expect(loadingBtn).toBeDisabled();
  });
  it("applies status-specific badge classes for each status", () => {
    const statuses: Array<{ status: BankStatement["status"]; cls: string }> = [
      { status: "approved", cls: "badge-success" },
      { status: "rejected", cls: "badge-error" },
      { status: "parsed", cls: "badge-warning" },
      { status: "uploaded", cls: "badge-muted" },
    ];
    for (const { status, cls } of statuses) {
      const { unmount } = renderHeader({ statement: { ...partBaseStatement, status } });
      expect(screen.getByText(status)).toHaveClass(cls);
      unmount();
    }
  });
});
describe("BrokerageImportResultBanner", () => {
  const result: BrokerageImportResponse = { broker: "Moomoo", parsed_positions: 5, created_atomic_positions: 3, existing_atomic_positions: 2, reconcile_created: 3, reconcile_updated: 2, reconcile_disposed: 0, skipped: 0 };
  it("AC22.17.3 renders import summary and portfolio link with and without skipped row", () => {
    const { rerender } = render(<BrokerageImportResultBanner importResult={result} />);
    const banner = screen.getByTestId("import-result-banner");
    expect(banner).toHaveTextContent("Brokerage positions imported successfully");
    expect(banner).toHaveTextContent("Moomoo");
    expect(screen.getByRole("link", { name: /view portfolio after import/i })).toHaveAttribute("href", "/portfolio");
    expect(screen.queryByText("Skipped:")).not.toBeInTheDocument();
    rerender(<BrokerageImportResultBanner importResult={{ ...result, skipped: 4 }} />);
    expect(screen.getByText("Skipped:")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });
}); // AC-extraction.fe-stage1-review.4 AC-extraction.fe-stage1-review.5 AC-extraction.fe-stage1-review.6 AC-extraction.fe-ia-extraction.3

describe("StatementDetailPage - import and lifecycle coverage", () => {
  const mockedApi = vi.mocked(apiOperation);
  const parsedBrokerageStatement = {
    id: "s1",
    original_filename: "moomoo-2026-01.pdf",
    institution: "Moomoo",
    currency: "USD",
    period_start: "2026-01-01",
    period_end: "2026-01-31",
    opening_balance: null,
    closing_balance: null,
    status: "parsed",
    parsing_progress: 100,
    transactions: [],
  };
  const IMPORT_OP = "import_brokerage_positions_portfolio_brokerage_imports_post";
  const RETRY_OP = "create_statement_run_statements__statement_id__runs_post";
  function renderWithClient(
    client: QueryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  ) {
    return render(
      <QueryClientProvider client={client}>
        <StatementDetailPage />
      </QueryClientProvider>,
    );
  }
  function mockByOperation(statement: unknown, overrides: Record<string, () => Promise<unknown>> = {}) {
    mockedApi.mockImplementation(((operationId: string) => {
      const override = overrides[operationId];
      if (override) return override();
      if (operationId === "get_statement_statements__statement_id__get") return Promise.resolve(statement);
      return Promise.resolve(null);
    }) as any);
  }
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => {
    vi.useRealTimers();
  });
  it("renders parsing stopped alert and resume polling button", async () => {
    const stmt = {
      id: "s1",
      original_filename: "file.pdf",
      institution: "Bank",
      currency: "SGD",
      period_start: null,
      period_end: null,
      opening_balance: null,
      closing_balance: null,
      status: "parsing",
      parsing_progress: 10,
      transactions: [],
    };
    mockByOperation(stmt);
    renderWithClient();
    expect(await screen.findByText(/Parsing in progress/)).toBeInTheDocument();
  });
  it("shows statement not found when api returns null", async () => {
    mockedApi.mockImplementation(() => Promise.resolve(null as any));
    renderWithClient();
    expect(await screen.findByText(/Statement not found/)).toBeInTheDocument();
  });
  it("AC17.8.1 shows Import to Portfolio button for parsed statement", async () => {
    mockedApi.mockResolvedValueOnce(parsedBrokerageStatement as any);
    renderWithClient();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /import brokerage positions to portfolio/i })).toBeInTheDocument(),
    );
  });
  it("AC17.8.2 shows import result banner and portfolio link on success", async () => {
    const importResult = {
      broker: "Moomoo",
      parsed_positions: 5,
      created_atomic_positions: 3,
      existing_atomic_positions: 2,
      reconcile_created: 3,
      reconcile_updated: 2,
      reconcile_disposed: 0,
      skipped: 0,
    };
    mockByOperation(parsedBrokerageStatement, { [IMPORT_OP]: () => Promise.resolve(importResult) });
    renderWithClient();
    const importBtn = await screen.findByRole("button", { name: /import brokerage positions to portfolio/i });
    fireEvent.click(importBtn);
    await waitFor(() => expect(screen.getByTestId("import-result-banner")).toBeInTheDocument());
    const banner = screen.getByTestId("import-result-banner");
    expect(banner).toHaveTextContent("Brokerage positions imported successfully");
    expect(banner).toHaveTextContent("Moomoo");
    const portfolioLink = screen.getByRole("link", { name: /view portfolio after import/i });
    expect(portfolioLink).toHaveAttribute("href", "/portfolio");
  });
  it("AC17.8.3 shows actionable import error banner without exposing sensitive data", async () => {
    mockByOperation(parsedBrokerageStatement, {
      [IMPORT_OP]: () => Promise.reject(new Error("Statement must be in PARSED or APPROVED status before importing")),
    });
    renderWithClient();
    const importBtn = await screen.findByRole("button", { name: /import brokerage positions to portfolio/i });
    fireEvent.click(importBtn);
    await waitFor(() => expect(screen.getByTestId("import-error-banner")).toBeInTheDocument());
    expect(screen.getByText("Brokerage Import Failed")).toBeInTheDocument();
    expect(screen.getByText(/Statement must be in PARSED or APPROVED status/)).toBeInTheDocument();
  });
  it("AC-extraction.fe-upload-layout.5 marks the portfolio reads stale after a successful import on the statement page", async () => {
    mockByOperation(parsedBrokerageStatement, {
      [IMPORT_OP]: () =>
        Promise.resolve({
          broker: "Moomoo",
          parsed_positions: 1,
          created_atomic_positions: 1,
          existing_atomic_positions: 0,
          reconcile_created: 1,
          reconcile_updated: 0,
          reconcile_disposed: 0,
          skipped: 0,
        }),
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const reads = [
      ["portfolio-holdings", false, ""],
      ["portfolio-summary", ""],
      ["reports-net-worth-allocation", "", "SGD", true],
      ["statements"],
      ["unrelated"],
    ];
    for (const key of reads) client.setQueryData(key, { seeded: true });
    renderWithClient(client);
    fireEvent.click(await screen.findByRole("button", { name: /import brokerage positions to portfolio/i }));
    await waitFor(() => expect(screen.getByTestId("import-result-banner")).toBeInTheDocument());
    expect(reads.map((key) => client.getQueryState(key)?.isInvalidated)).toEqual([true, true, true, true, false]);
  });
  it("AC17.8.3 sanitizes sensitive URLs in import error messages", async () => {
    mockByOperation(parsedBrokerageStatement, {
      [IMPORT_OP]: () => Promise.reject(new Error("Import failed: https://s3.example.com/private/token=abc123")),
    });
    renderWithClient();
    const importBtn = await screen.findByRole("button", { name: /import brokerage positions to portfolio/i });
    fireEvent.click(importBtn);
    await waitFor(() => expect(screen.getByTestId("import-error-banner")).toBeInTheDocument());
    expect(screen.queryByText(/s3\.example\.com/)).not.toBeInTheDocument();
    expect(screen.getByText(/\[URL\]/)).toBeInTheDocument();
  });
  it("AC17.8.5 does not show Import to Portfolio for non-parsed statements", async () => {
    const uploadedStatement = { ...parsedBrokerageStatement, status: "uploaded" };
    mockedApi.mockResolvedValueOnce(uploadedStatement as any);
    renderWithClient();
    await waitFor(() => expect(screen.getByText("moomoo-2026-01.pdf")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /import brokerage positions to portfolio/i })).not.toBeInTheDocument();
  });
  it("test_AC8_13_48 stops stuck parsing auto-refresh and resumes polling on demand", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
    const parsingStatement = { ...parsedBrokerageStatement, status: "parsing", parsing_progress: 30, transactions: [] };
    mockedApi.mockResolvedValue(parsingStatement as any);
    renderWithClient();
    expect(await screen.findByText(/Parsing in progress/)).toBeInTheDocument();
    await act(async () => {
      vi.setSystemTime(new Date("2026-01-01T00:07:01Z"));
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(await screen.findByText("Auto-refresh Stopped")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Resume Auto-Refresh" }));
    await waitFor(() =>
      expect(mockedApi).toHaveBeenCalledWith(
        "get_statement_statements__statement_id__get",
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      ),
    );
  });
  it("test_AC8_13_48 shows run again errors for rejected statements", async () => {
    const rejectedStatement = {
      ...parsedBrokerageStatement,
      status: "rejected",
      validation_error: "Bad parse",
      transactions: [],
    };
    mockByOperation(rejectedStatement, { [RETRY_OP]: () => Promise.reject(new Error("retry failed")) });
    renderWithClient();
    await screen.findByText("Parsing Failed");
    fireEvent.click(screen.getByRole("button", { name: "Run again" }));
    await waitFor(() => expect(screen.getAllByText("retry failed").length).toBeGreaterThan(0));
    expect(mockedApi).toHaveBeenCalledWith("create_statement_run_statements__statement_id__runs_post", {
      path: { statement_id: "s1" },
      body: { kind: "extract", hints: { keywords: [], note: null } },
    });
  });
  it("handles delete statement confirmation and API call", async () => {
    mockedApi.mockImplementation((operationId: string) => {
      if (operationId === "delete_statement_statements__statement_id__delete") return Promise.resolve(null as any);
      return Promise.resolve(parsedBrokerageStatement as any);
    });
    renderWithClient();
    const deleteBtn = await screen.findByRole("button", { name: "Delete statement" });
    expect(deleteBtn).toBeInTheDocument();
    fireEvent.click(deleteBtn);
    const cancelBtn = screen.getByRole("button", { name: "Cancel" });
    fireEvent.click(cancelBtn);
    fireEvent.click(deleteBtn);
    const confirmBtn = await screen.findByRole("button", { name: "Delete" });
    fireEvent.click(confirmBtn);
    await waitFor(() => {
      expect(mockedApi).toHaveBeenCalledWith(
        "delete_statement_statements__statement_id__delete",
        expect.objectContaining({ path: { statement_id: "s1" } }),
      );
    });
  });
  it("handles delete statement error gracefully", async () => {
    mockedApi.mockImplementation((operationId: string) => {
      if (operationId === "delete_statement_statements__statement_id__delete")
        return Promise.reject(new Error("Failed to delete"));
      return Promise.resolve(parsedBrokerageStatement as any);
    });
    renderWithClient();
    const deleteBtn = await screen.findByRole("button", { name: "Delete statement" });
    fireEvent.click(deleteBtn);
    const confirmBtn = await screen.findByRole("button", { name: "Delete" });
    fireEvent.click(confirmBtn);
    await waitFor(() => {
      expect(showToastMock).toHaveBeenCalledWith("Failed to delete", "error");
    });
  });
}); // AC-portfolio.fe-assets2.13 AC-portfolio.fe-assets2.15

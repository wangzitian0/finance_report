import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import StatementDetailPage from "@/app/(main)/statements/[id]/page";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { ApiError, apiOperation } from "@/lib/api-client";
import { LEDGER_DERIVED_QUERY_KEYS } from "@/lib/queryClient";
import type { StatementRun } from "@/lib/types";

const showToastMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useParams: () => ({ id: "s1" }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast: showToastMock }) }));
vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  apiOperation: vi.fn(),
}));

const RUNS_GET = "list_statement_runs_statements__statement_id__runs_get";
const RUNS_POST = "create_statement_run_statements__statement_id__runs_post";
const REJECT_POST = "reject_statement_stage1_statements__statement_id__review_reject_post";

const statement = {
  id: "s1",
  original_filename: "statement-jan.pdf",
  institution: "DBS",
  currency: "SGD",
  period_start: "2026-01-01",
  period_end: "2026-01-31",
  opening_balance: 1000,
  closing_balance: 1500,
  confidence_score: 92,
  balance_validated: true,
  validation_error: null,
  status: "rejected",
  parsing_progress: 100,
  transactions: [],
};

function makeRun(overrides: Partial<StatementRun> = {}): StatementRun {
  return {
    id: `run-${overrides.seq ?? 1}`,
    seq: 1,
    kind: "extract",
    state: "succeeded",
    actor_kind: "user",
    trigger: "rerun",
    parent_run_id: null,
    hints: { keywords: [], note: null },
    model: null,
    prompt_template_version: "1",
    prompt_digest: "d".repeat(64),
    error_code: null,
    error_message: null,
    requested_at: "2026-01-05T08:00:00Z",
    started_at: "2026-01-05T08:00:01Z",
    finished_at: "2026-01-05T08:00:30Z",
    ...overrides,
  };
}

const mockedApi = vi.mocked(apiOperation);

function mockApi(options: {
  status?: string;
  runs: () => StatementRun[];
  post?: (body: unknown) => Promise<unknown>;
  reject?: (body: unknown) => Promise<unknown>;
}) {
  mockedApi.mockImplementation(((operationId: string, request?: { body?: unknown }) => {
    switch (operationId) {
      case "get_statement_statements__statement_id__get":
        return Promise.resolve({ ...statement, status: options.status ?? "rejected" });
      case "get_statement_for_review_statements__statement_id__review_get":
        return Promise.resolve({ ...statement, status: options.status ?? "rejected", balance_validation_result: null, source_missing_facts: [], source_envelope_reviewable: false, reviewed_envelope: null });
      case "list_pending_review_statements_pending_review_get":
        return Promise.resolve({ items: [], total: 0 });
      case "get_review_conflicts_review_conflicts__statement_id__get":
        return Promise.resolve({ duplicates: [], transfer_pairs: [], resolved: true });
      case RUNS_GET: {
        const items = options.runs();
        return Promise.resolve({ items, total: items.length });
      }
      case RUNS_POST:
        return options.post ? options.post(request?.body) : Promise.resolve(makeRun({ seq: 9 }));
      case REJECT_POST:
        return options.reject ? options.reject(request?.body) : Promise.resolve({ ...statement, status: "rejected" });
      default:
        return Promise.reject(new Error(`Unexpected operation ${operationId}`));
    }
  }) as unknown as typeof apiOperation);
}

const STATEMENT_GET = "get_statement_statements__statement_id__get";
const REVIEW_GET = "get_statement_for_review_statements__statement_id__review_get";
const callsOf = (operationId: string) => mockedApi.mock.calls.filter((call) => call[0] === operationId);
const runPosts = () => mockedApi.mock.calls.filter((call) => call[0] === RUNS_POST);
const runListCalls = () => mockedApi.mock.calls.filter((call) => call[0] === RUNS_GET);
const runAgainButton = () => screen.getByRole("button", { name: "Run again" });
const keywordField = () => screen.getByRole("textbox", { name: /Keywords/ });
const noteField = () => screen.getByRole("textbox", { name: /Note/ });

describe("Parsing attempts and Run again on the statement page", () => {
  beforeEach(() => {
    mockedApi.mockReset();
    showToastMock.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("AC-extraction.2994.56 lists each attempt, newest first, with actor, trigger, state, hints and error code", async () => {
    mockApi({
      runs: () => [
        makeRun({ seq: 1, actor_kind: "system", trigger: "upload", state: "failed", error_code: "extraction_error", error_message: "The parse failed." }),
        makeRun({ seq: 2, actor_kind: "user", trigger: "rerun", state: "succeeded", hints: { keywords: ["interest", "FX fee"], note: "Credits carry a CR suffix.\nYear is 2026." } }),
      ],
    });

    render(<StatementDetailPage />);

    const list = await screen.findByTestId("parsing-attempts");
    const attempts = within(list).getAllByRole("listitem").filter((item) => item.dataset.testid?.startsWith("parsing-attempt-"));
    expect(attempts.map((item) => item.dataset.testid)).toEqual(["parsing-attempt-2", "parsing-attempt-1"]);
    const second = within(screen.getByTestId("parsing-attempt-2"));
    expect(second.getByText("Attempt 2")).toBeInTheDocument();
    expect(second.getByText("User · Rerun")).toBeInTheDocument();
    expect(second.getByText("Succeeded")).toBeInTheDocument();
    const chips = within(second.getByRole("list", { name: "Keywords of attempt 2" })).getAllByRole("listitem");
    expect(chips.map((chip) => chip.textContent)).toEqual(["interest", "FX fee"]);
    expect(second.getByText(/Note: Credits carry a CR suffix\./)).toHaveTextContent("Year is 2026.");
    const first = within(screen.getByTestId("parsing-attempt-1"));
    expect(first.getByText("System · Upload")).toBeInTheDocument();
    expect(first.getByText("Failed")).toBeInTheDocument();
    expect(first.getByText("Error: extraction_error")).toBeInTheDocument();
    expect(first.getByText("No hints")).toBeInTheDocument();
  });

  it("AC-extraction.2994.57 posts the hints exactly as typed through the runs operation", async () => {
    mockApi({ runs: () => [makeRun({ seq: 1, state: "failed", error_code: "extraction_error" })] });
    render(<StatementDetailPage />);
    await screen.findByTestId("run-again-panel");

    fireEvent.change(keywordField(), { target: { value: "interest, FX fee\n  salary ,\n\n" } });
    fireEvent.change(noteField(), { target: { value: "  Credits carry a CR suffix.\n  Second line.\n" } });
    fireEvent.click(runAgainButton());

    await waitFor(() => expect(runPosts()).toHaveLength(1));
    expect(runPosts()[0]).toEqual([
      RUNS_POST,
      {
        path: { statement_id: "s1" },
        body: { kind: "extract", hints: { keywords: ["interest", "FX fee", "salary"], note: "  Credits carry a CR suffix.\n  Second line.\n" } },
      },
    ]);
    await waitFor(() => expect(keywordField()).toHaveValue(""));
    expect(noteField()).toHaveValue("");
  });

  it("AC-extraction.2994.57 posts a null note and no keywords when both fields are empty", async () => {
    mockApi({ runs: () => [] });
    render(<StatementDetailPage />);
    await screen.findByTestId("run-again-panel");

    fireEvent.change(noteField(), { target: { value: "   " } });
    fireEvent.click(runAgainButton());

    await waitFor(() => expect(runPosts()).toHaveLength(1));
    expect(runPosts()[0][1]).toMatchObject({ body: { kind: "extract", hints: { keywords: [], note: null } } });
  });

  it("AC-extraction.2994.58 disables Run again while a run is active, refetches the attempts, and enables it when the run ends", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let state: StatementRun["state"] = "running";
    mockApi({ runs: () => [makeRun({ seq: 1, state, finished_at: state === "running" ? null : "2026-01-05T08:01:00Z" })] });
    render(<StatementDetailPage />);

    expect(await screen.findByText(/A parse is running/)).toBeInTheDocument();
    expect(runAgainButton()).toBeDisabled();
    fireEvent.click(runAgainButton());
    expect(runPosts()).toHaveLength(0);
    const callsWhileActive = runListCalls().length;

    state = "succeeded";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });
    await waitFor(() => expect(runAgainButton()).toBeEnabled());
    expect(screen.queryByText(/A parse is running/)).not.toBeInTheDocument();
    expect(runListCalls().length).toBeGreaterThan(callsWhileActive);

    const callsAfterEnd = runListCalls().length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000);
    });
    expect(runListCalls().length).toBe(callsAfterEnd);
  });

  it("AC-extraction.2994.58 disables Run again for a requested run too", async () => {
    mockApi({ runs: () => [makeRun({ seq: 1, state: "requested", started_at: null, finished_at: null })] });
    render(<StatementDetailPage />);

    await screen.findByText(/A parse is running/);

    expect(runAgainButton()).toBeDisabled();
  });

  it("AC-extraction.2994.63 refetches the statement, the review and the attempts after a run starts", async () => {
    mockApi({ runs: () => [makeRun({ seq: 1, state: "failed", error_code: "extraction_error" })] });
    const invalidate = vi.spyOn(QueryClient.prototype, "invalidateQueries");
    try {
      render(<StatementDetailPage />);
      await screen.findByTestId("run-again-panel");
      await waitFor(() => expect(callsOf(REVIEW_GET).length).toBeGreaterThan(0));
      const before = { statement: callsOf(STATEMENT_GET).length, review: callsOf(REVIEW_GET).length, runs: runListCalls().length };
      invalidate.mockClear();

      fireEvent.click(runAgainButton());

      await waitFor(() => expect(runPosts()).toHaveLength(1));
      await waitFor(() => expect(callsOf(STATEMENT_GET).length).toBeGreaterThan(before.statement));
      await waitFor(() => expect(callsOf(REVIEW_GET).length).toBeGreaterThan(before.review));
      await waitFor(() => expect(runListCalls().length).toBeGreaterThan(before.runs));
      // The exact keys: the attempts of this statement and every ledger-derived read, which includes the review.
      const keys = invalidate.mock.calls.map((call) => JSON.stringify((call[0] as { queryKey?: unknown } | undefined)?.queryKey));
      expect(keys).toContain(JSON.stringify(["statement-runs", "s1"]));
      for (const key of LEDGER_DERIVED_QUERY_KEYS) expect(keys).toContain(JSON.stringify(key));
      expect(keys).toContain(JSON.stringify(["statement-review"]));
    } finally {
      invalidate.mockRestore();
    }
  });

  it("AC-extraction.2994.59 names the active run when the 409 body carries active_run_id", async () => {
    const body = { error_id: "conflict", message: "The statement has an active run.", active_run_id: "run-active" };
    mockApi({
      runs: () => [makeRun({ seq: 1, state: "failed", error_code: "extraction_error" })],
      post: () => Promise.reject(new ApiError(body.message, 409, "conflict", null, body as never)),
    });
    render(<StatementDetailPage />);
    await screen.findByTestId("run-again-panel");

    fireEvent.click(runAgainButton());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("A parse is already running for this statement. Wait for it to end, then run again.");
    expect(showToastMock).toHaveBeenCalledWith(expect.stringContaining("already running"), "error");
  });

  it("AC-extraction.2994.59 says that the statement changed for a 409 without an active run", async () => {
    const body = { error_id: "conflict", message: "The statement changed while the run started." };
    mockApi({
      runs: () => [makeRun({ seq: 1, state: "failed", error_code: "extraction_error" })],
      post: () => Promise.reject(new ApiError(body.message, 409, "conflict", null, body as never)),
    });
    render(<StatementDetailPage />);
    await screen.findByTestId("run-again-panel");

    fireEvent.click(runAgainButton());

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("The statement changed. Reload the page.");
    expect(screen.queryByText(/already running/)).not.toBeInTheDocument();
    expect(showToastMock).toHaveBeenCalledWith("The statement changed. Reload the page.", "error");
  });

  it("AC-extraction.2994.60 enforces 20 keywords of 64 characters and a note of 500 characters", async () => {
    mockApi({ runs: () => [] });
    render(<StatementDetailPage />);
    await screen.findByTestId("run-again-panel");
    const keywords = (count: number, length = 5) => Array.from({ length: count }, (_, index) => `${index}`.padEnd(length, "k")).join(", ");

    expect(noteField()).toHaveAttribute("maxlength", "500");

    fireEvent.change(keywordField(), { target: { value: keywords(20, 64) } });
    expect(runAgainButton()).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    fireEvent.change(keywordField(), { target: { value: keywords(21) } });
    expect(runAgainButton()).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("Use at most 20 keywords.");

    fireEvent.change(keywordField(), { target: { value: keywords(1, 65) } });
    expect(runAgainButton()).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("Each keyword has at most 64 characters.");

    fireEvent.change(keywordField(), { target: { value: keywords(1, 64) } });
    expect(runAgainButton()).toBeEnabled();
    expect(runPosts()).toHaveLength(0);
  });

  it("AC-extraction.2994.72 refuses control characters before the request", async () => {
    mockApi({ runs: () => [] });
    render(<StatementDetailPage />);
    await screen.findByTestId("run-again-panel");
    const message = "Keywords and the note cannot contain control characters.";

    for (const bad of ["\u0007", "\u0000", "\u200e\u0085"]) {
      fireEvent.change(keywordField(), { target: { value: `interest, bad${bad}word` } });
      expect(runAgainButton(), `keyword with U+${bad.charCodeAt(0).toString(16)}`).toBeDisabled();
      expect(screen.getByRole("alert")).toHaveTextContent(message);
    }
    fireEvent.change(keywordField(), { target: { value: "interest" } });
    expect(runAgainButton()).toBeEnabled();

    for (const bad of ["\u0007", "\r"]) {
      fireEvent.change(noteField(), { target: { value: `first${bad}second` } });
      expect(runAgainButton(), `note with U+${bad.charCodeAt(0).toString(16)}`).toBeDisabled();
      expect(screen.getByRole("alert")).toHaveTextContent(message);
    }
    fireEvent.change(noteField(), { target: { value: "first line\n\tsecond line, with a tab" } });
    expect(runAgainButton()).toBeEnabled();
    expect(runPosts()).toHaveLength(0);
  });

  it("AC-extraction.2994.80 turns U+2028 and U+2029 into a new line in the note and a space in a keyword", async () => {
    mockApi({ runs: () => [] });
    render(<StatementDetailPage />);
    await screen.findByTestId("run-again-panel");

    fireEvent.change(keywordField(), { target: { value: "FX\u2028fee, rent\u2029due" } });
    fireEvent.change(noteField(), { target: { value: "first\u2028second\u2029third" } });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(runAgainButton()).toBeEnabled();
    fireEvent.click(runAgainButton());

    await waitFor(() => expect(runPosts()).toHaveLength(1));
    expect(runPosts()[0][1]).toMatchObject({
      body: { kind: "extract", hints: { keywords: ["FX fee", "rent due"], note: "first\nsecond\nthird" } },
    });
  });

  it("AC-extraction.2994.72 keeps zero width joiners valid", async () => {
    mockApi({ runs: () => [] });
    render(<StatementDetailPage />);
    await screen.findByTestId("run-again-panel");

    fireEvent.change(keywordField(), { target: { value: "می\u200cخواهم" } });
    fireEvent.change(noteField(), { target: { value: "a\u200db" } });

    expect(runAgainButton()).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("AC-extraction.2994.73 shows one fixed sentence for a 422 and never the raw body", async () => {
    const raw = JSON.stringify({ detail: [{ type: "value_error", loc: ["body", "hints", "keywords"], input: ["SECRET-KEYWORD"] }] });
    mockApi({ runs: () => [], post: () => Promise.reject(new ApiError(raw, 422, "validation_error")) });
    render(<StatementDetailPage />);
    await screen.findByTestId("run-again-panel");
    fireEvent.change(keywordField(), { target: { value: "SECRET-KEYWORD" } });

    fireEvent.click(runAgainButton());

    const fixed = "The hints are not valid. Check the keywords and the note.";
    expect(await screen.findByRole("alert")).toHaveTextContent(fixed);
    expect(screen.getByRole("alert").textContent).toBe(fixed);
    expect(showToastMock).toHaveBeenCalledWith(fixed, "error");
    // The user's own text stays in the keyword field. Nothing else on the page may repeat it.
    expect(screen.queryAllByText(/SECRET-KEYWORD/).filter((element) => element.tagName !== "TEXTAREA")).toEqual([]);
    expect(screen.queryByText(/"detail"/)).not.toBeInTheDocument();
    expect(JSON.stringify(showToastMock.mock.calls)).not.toContain("SECRET-KEYWORD");
  });

  it("AC-extraction.2994.74 lists the attempts while the statement is parsing, with the failed attempt that explains it", async () => {
    mockApi({
      status: "parsing",
      runs: () => [
        makeRun({ seq: 1, state: "failed", error_code: "heartbeat_lost", actor_kind: "system", trigger: "upload" }),
        makeRun({ seq: 2, state: "running", actor_kind: "system", trigger: "auto_retry", finished_at: null }),
      ],
    });
    render(<StatementDetailPage />);

    const list = await screen.findByTestId("parsing-attempts");

    expect(within(list).getByText("Error: heartbeat_lost")).toBeInTheDocument();
    expect(within(screen.getByTestId("parsing-attempt-2")).getByText("Running")).toBeInTheDocument();
    expect(screen.getByText(/Parsing in progress/)).toBeInTheDocument();
  });

  it("AC-extraction.2994.74 disables Run again for a stuck parsing statement while a run is active", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
    mockApi({ status: "parsing", runs: () => [makeRun({ seq: 1, state: "running", finished_at: null })] });
    render(<StatementDetailPage />);
    await screen.findByText(/Parsing in progress/);

    await act(async () => {
      vi.setSystemTime(new Date("2026-01-01T00:05:01Z"));
      await vi.advanceTimersByTimeAsync(3100);
    });

    expect(await screen.findByText("Auto-refresh Stopped")).toBeInTheDocument();
    expect(await screen.findByText(/A parse is running/)).toBeInTheDocument();
    expect(runAgainButton()).toBeDisabled();
  });

  it("AC-extraction.2994.81 sends a reject note with U+2028 and U+2029 as new lines", async () => {
    mockApi({ status: "parsed", runs: () => [] });
    render(<StatementDetailPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
    const dialog = await screen.findByRole("dialog", { name: "Reject Statement" });

    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "first\u2028second\u2029third" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Reject" }));

    await waitFor(() => expect(callsOf(REJECT_POST)).toHaveLength(1));
    expect(callsOf(REJECT_POST)[0][1]).toMatchObject({ body: { notes: "first\nsecond\nthird" } });
  });

  it("AC-extraction.2994.81 refuses a reject note with a control character and sends nothing", async () => {
    mockApi({ status: "parsed", runs: () => [] });
    render(<StatementDetailPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
    const dialog = await screen.findByRole("dialog", { name: "Reject Statement" });

    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "bad\u0007note" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Reject" }));

    await waitFor(() => expect(showToastMock).toHaveBeenCalledWith("Keywords and the note cannot contain control characters.", "error"));
    expect(callsOf(REJECT_POST)).toHaveLength(0);
  });

  it("AC-extraction.2994.82 shows one fixed sentence for a 422 of the reject and never the raw body", async () => {
    const raw = JSON.stringify({ detail: [{ type: "value_error", input: "SECRET-REJECT-NOTE" }] });
    mockApi({ status: "parsed", runs: () => [], reject: () => Promise.reject(new ApiError(raw, 422, "validation_error")) });
    render(<StatementDetailPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
    const dialog = await screen.findByRole("dialog", { name: "Reject Statement" });

    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "SECRET-REJECT-NOTE" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Reject" }));

    const fixed = "The hints are not valid. Check the keywords and the note.";
    await waitFor(() => expect(showToastMock).toHaveBeenCalledWith(fixed, "error"));
    expect(JSON.stringify(showToastMock.mock.calls)).not.toContain("SECRET-REJECT-NOTE");
  });

  it("AC-extraction.2994.61 limits the note of the reject dialog to 500 characters", async () => {
    mockApi({ status: "parsed", runs: () => [] });
    render(<StatementDetailPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));

    const dialog = await screen.findByRole("dialog", { name: "Reject Statement" });
    expect(within(dialog).getByRole("textbox")).toHaveAttribute("maxlength", "500");
  });

  it("AC-extraction.2994.61 ConfirmDialog sets maxLength on its input only when the prop is given", () => {
    const { rerender } = render(
      <ConfirmDialog isOpen title="T" message="M" input={{ label: "Reason", maxLength: 12 }} onConfirm={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(screen.getByRole("textbox")).toHaveAttribute("maxlength", "12");

    rerender(<ConfirmDialog isOpen title="T" message="M" input={{ label: "Reason" }} onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByRole("textbox")).not.toHaveAttribute("maxlength");
  });

  it("AC-extraction.2994.62 offers no Run again for an approved statement and has no Retry Parse button", async () => {
    mockApi({ status: "approved", runs: () => [makeRun({ seq: 1 })] });
    render(<StatementDetailPage />);

    await screen.findByTestId("parsing-attempts");

    expect(screen.queryByTestId("run-again-panel")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry Parse" })).not.toBeInTheDocument();
  });
});

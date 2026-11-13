import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import StatementDetailPage from "@/app/(main)/statements/[id]/page";
import { ApiError, apiOperation } from "@/lib/api-client";
import type { StatementRun } from "@/lib/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useParams: () => ({ id: "s1" }),
  useSearchParams: () => new URLSearchParams(),
}));
const showToastMock = vi.fn();
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast: showToastMock }) }));
vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  apiOperation: vi.fn(),
}));

const REVIEW_GET = "get_statement_for_review_statements__statement_id__review_get";
const STATEMENT_GET = "get_statement_statements__statement_id__get";
const RUNS_GET = "list_statement_runs_statements__statement_id__runs_get";
const APPROVE_POST = "approve_statement_stage1_statements__statement_id__review_approve_post";
const REJECT_POST = "reject_statement_stage1_statements__statement_id__review_reject_post";
const CONFIRM_POST = "confirm_statement_review_envelope_statements__statement_id__review_envelope_post";
const NOTICE = "Classifying transactions…";
const BLOCKED = "Wait for the active run to end before approving this statement.";

const validBalance = {
  opening_balance: "1000.00",
  closing_balance: "1500.00",
  calculated_closing: "1500.00",
  opening_delta: "0.00",
  closing_delta: "0.00",
  opening_match: true,
  closing_match: true,
  validated_at: "2026-01-31T00:00:00Z",
};

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
  validation_error: "Economic review required: 2 rows need review",
  status: "parsed",
  parsing_progress: 100,
  transactions: [],
};

function makeRun(overrides: Partial<StatementRun> = {}): StatementRun {
  return {
    id: `run-${overrides.seq ?? 1}`,
    seq: 1,
    kind: "extract",
    state: "succeeded",
    actor_kind: "system",
    trigger: "upload",
    parent_run_id: null,
    hints: { keywords: [], note: null },
    model: null,
    prompt_template_version: null,
    prompt_digest: null,
    error_code: null,
    error_message: null,
    requested_at: "2026-01-05T08:00:00Z",
    started_at: "2026-01-05T08:00:01Z",
    finished_at: "2026-01-05T08:00:30Z",
    ...overrides,
  };
}

const classifyRun = (state: StatementRun["state"]) =>
  makeRun({
    seq: 2,
    kind: "classify",
    state,
    trigger: "auto_classify",
    parent_run_id: "run-1",
    finished_at: state === "requested" || state === "running" ? null : "2026-01-05T08:00:40Z",
  });

const mockedApi = vi.mocked(apiOperation);
const callsOf = (operationId: string) => mockedApi.mock.calls.filter((call) => call[0] === operationId);

function mockApi(
  runs: () => StatementRun[],
  extra: { review?: Record<string, unknown>; post?: (operationId: string) => Promise<unknown> } = {},
) {
  mockedApi.mockImplementation(((operationId: string) => {
    switch (operationId) {
      case STATEMENT_GET:
        return Promise.resolve(statement);
      case REVIEW_GET:
        return Promise.resolve({
          ...statement,
          balance_validation_result: validBalance,
          source_missing_facts: [],
          source_envelope_reviewable: false,
          reviewed_envelope: { id: "e1" },
          account_id: "a1",
          ...extra.review,
        });
      case "list_pending_review_statements_pending_review_get":
        return Promise.resolve({ items: [], total: 0 });
      case "get_review_conflicts_review_conflicts__statement_id__get":
        return Promise.resolve({ duplicates: [], transfer_pairs: [], resolved: true });
      case RUNS_GET: {
        const items = runs();
        return Promise.resolve({ items, total: items.length });
      }
      case APPROVE_POST:
      case REJECT_POST:
      case CONFIRM_POST:
        return extra.post ? extra.post(operationId) : Promise.reject(new Error(`Unexpected operation ${operationId}`));
      default:
        return Promise.reject(new Error(`Unexpected operation ${operationId}`));
    }
  }) as unknown as typeof apiOperation);
}

const approveButton = () => screen.getByRole("button", { name: "Approve" });
const autoFillButton = () => screen.getByRole("button", { name: /Auto-Fill Default Categories/ });

describe("The classify run on the statement page", () => {
  beforeEach(() => {
    mockedApi.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("AC-extraction.2994.105 shows the classifying notice and blocks the approve and the auto-fill while a classify run is active", async () => {
    mockApi(() => [makeRun({ seq: 1 }), classifyRun("running")]);
    render(<StatementDetailPage />);

    expect(await screen.findByText(NOTICE)).toBeInTheDocument();
    await waitFor(() => expect(approveButton()).toBeDisabled());
    expect(screen.getByText(BLOCKED)).toBeInTheDocument();
    expect(autoFillButton()).toBeDisabled();
    expect(callsOf(REVIEW_GET).length).toBeGreaterThan(0);
  });

  it("AC-extraction.2994.105 treats a requested classify run as active", async () => {
    mockApi(() => [makeRun({ seq: 1 }), classifyRun("requested")]);
    render(<StatementDetailPage />);

    expect(await screen.findByText(NOTICE)).toBeInTheDocument();
    await waitFor(() => expect(approveButton()).toBeDisabled());
  });

  it("AC-extraction.2994.105 blocks the approve and the auto-fill for an active extract run too, with no classifying notice", async () => {
    mockApi(() => [makeRun({ seq: 1, state: "running", finished_at: null })]);
    render(<StatementDetailPage />);

    await screen.findByTestId("parsing-attempts");

    await waitFor(() => expect(approveButton()).toBeDisabled());
    expect(screen.getByText(BLOCKED)).toBeInTheDocument();
    expect(autoFillButton()).toBeDisabled();
    expect(screen.queryByText(NOTICE)).not.toBeInTheDocument();
  });

  it("AC-extraction.2994.105 enables the approve and reads the review again when the classify run ends", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let state: StatementRun["state"] = "running";
    mockApi(() => [makeRun({ seq: 1 }), classifyRun(state)]);
    render(<StatementDetailPage />);
    expect(await screen.findByText(NOTICE)).toBeInTheDocument();
    await waitFor(() => expect(approveButton()).toBeDisabled());
    const reviewCallsWhileActive = callsOf(REVIEW_GET).length;
    const statementCallsWhileActive = callsOf(STATEMENT_GET).length;

    state = "succeeded";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });

    await waitFor(() => expect(screen.queryByText(NOTICE)).not.toBeInTheDocument());
    await waitFor(() => expect(approveButton()).toBeEnabled());
    expect(autoFillButton()).toBeEnabled();
    await waitFor(() => expect(callsOf(REVIEW_GET).length).toBeGreaterThan(reviewCallsWhileActive));
    await waitFor(() => expect(callsOf(STATEMENT_GET).length).toBeGreaterThan(statementCallsWhileActive));
  });

  it("AC-extraction.2994.106 lists the kind of each attempt, classify runs too", async () => {
    mockApi(() => [makeRun({ seq: 1 }), classifyRun("succeeded")]);
    render(<StatementDetailPage />);

    await screen.findByTestId("parsing-attempts");

    expect(within(screen.getByTestId("parsing-attempt-1")).getByText("Extract")).toBeInTheDocument();
    const second = within(screen.getByTestId("parsing-attempt-2"));
    expect(second.getByText("Classify")).toBeInTheDocument();
    expect(second.getByText("System · Auto Classify")).toBeInTheDocument();
    expect(second.getByText("Succeeded")).toBeInTheDocument();
  });
  it("AC-extraction.2994.113 keeps the source-facts confirmation available while a classify run is active", async () => {
    mockApi(() => [makeRun({ seq: 1 }), classifyRun("running")], {
      review: { reviewed_envelope: null, source_envelope_reviewable: true, source_result_digest: "digest-1" },
      post: () => Promise.resolve({ id: "env-1" }),
    });
    render(<StatementDetailPage />);
    expect(await screen.findByText(NOTICE)).toBeInTheDocument();

    const rationale = await screen.findByLabelText(/Why are these facts confirmed/);
    fireEvent.change(rationale, { target: { value: "Checked against the original file." } });
    const confirm = await screen.findByRole("button", { name: "Confirm statement details" });

    await waitFor(() => expect(confirm).toBeEnabled());
    fireEvent.click(confirm);
    await waitFor(() => expect(callsOf(CONFIRM_POST)).toHaveLength(1));
  });

  it.each(["auto-fill", "reject"])(
    "AC-extraction.2994.114 reads the runs and the review again when the %s returns 409, and shows the run that began elsewhere",
    async (action) => {
      let runs: StatementRun[] = [makeRun({ seq: 1 })];
      const conflict = new ApiError("The statement has an active run.", 409, "conflict", null, { active_run_id: "run-2" } as never);
      mockApi(() => runs, { post: () => Promise.reject(conflict) });
      render(<StatementDetailPage />);
      await screen.findByTestId("parsing-attempts");
      await waitFor(() => expect(approveButton()).toBeEnabled());
      const runCalls = callsOf(RUNS_GET).length;
      const reviewCalls = callsOf(REVIEW_GET).length;
      runs = [makeRun({ seq: 1 }), classifyRun("running")]; // another tab started the run

      if (action === "auto-fill") {
        fireEvent.click(autoFillButton());
      } else {
        fireEvent.click(screen.getByRole("button", { name: "Reject" }));
        const dialog = await screen.findByRole("dialog", { name: "Reject Statement" });
        fireEvent.click(within(dialog).getByRole("button", { name: "Reject" }));
      }

      await waitFor(() => expect(callsOf(action === "auto-fill" ? APPROVE_POST : REJECT_POST)).toHaveLength(1));
      await waitFor(() => expect(callsOf(RUNS_GET).length).toBeGreaterThan(runCalls));
      await waitFor(() => expect(callsOf(REVIEW_GET).length).toBeGreaterThan(reviewCalls));
      expect(await screen.findByText(NOTICE)).toBeInTheDocument();
      await waitFor(() => expect(approveButton()).toBeDisabled());
    },
  );
});

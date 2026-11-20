import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import StatementDetailPage from "@/app/(main)/statements/[id]/page";
import { ApiError, apiOperation } from "@/lib/api";
import * as F from "./helpers/statementTestFixtures";

// #3029 item 3: the Re-parse button of the review bar and its 409 message follow a classify run.

const showToastMock = vi.fn();
vi.mock("next/navigation", async () => (await import("./helpers/statementTestFixtures")).navS1Mock());
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast: showToastMock }) }));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  apiOperation: vi.fn(),
  apiOperationDownload: vi.fn(() => import("./helpers/statementTestFixtures").then((m) => m.apiDlMock())),
}));

const api = vi.mocked(apiOperation);
const GENERIC_409 = "A run is already in progress for this statement. Wait for it to end, then run again.";
const CLASSIFY_409 = "A classification run is already in progress for this statement. Wait for it to end, then run again.";
const BACKEND_409 = "The statement has an active run. Wait for it to end.";

type Run = ReturnType<typeof F.mkRun>;

// A parsed statement whose closing balance does not match: the review bar then offers Re-parse.
const mismatchApi = (runs: () => Run[], post?: () => Promise<unknown>) =>
  F.mockStmtApi(api, {
    stmt: F.REV.stmt,
    rev: { ...F.REV.stmt, balance_validation_result: F.REV.mismatchBal },
    runs,
    extra: (op) => (op === F.OP.RUN_POST && post ? post() : undefined),
  });

describe("Statement page and a classify run (#3029 item 3)", () => {
  beforeEach(() => {
    api.mockReset();
    showToastMock.mockReset();
  });

  it("shows no Re-parse button while a classify run is active", async () => {
    mismatchApi(() => [F.mkClassifyRun("running", { seq: 1, parent_run_id: null })]);
    render(<StatementDetailPage />);
    await screen.findByText(/Wait for the active run to end before approving/i);
    expect(screen.queryByRole("button", { name: /Re-parse statement/i })).not.toBeInTheDocument();
  });

  it("shows the Re-parse button when the classify run has ended", async () => {
    mismatchApi(() => [F.mkClassifyRun("succeeded", { seq: 1, parent_run_id: null })]);
    render(<StatementDetailPage />);
    expect(await screen.findByRole("button", { name: /Re-parse statement/i })).toBeEnabled();
  });

  it("names the classify run in the 409 message of Re-parse", async () => {
    // The page does not know the run yet: it began in the worker after the last poll. The 409 body holds only its id.
    let started = false;
    mismatchApi(
      () => (started ? [F.mkClassifyRun("running", { id: "run-5", seq: 1, parent_run_id: null })] : []),
      () => {
        started = true;
        return F.err409(ApiError, BACKEND_409, { active_run_id: "run-5" })();
      },
    );
    render(<StatementDetailPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Re-parse statement/i }));
    await waitFor(() => expect(showToastMock).toHaveBeenCalledWith(CLASSIFY_409, "error"));
    // The runs refresh: the page now knows the run and hides the button.
    await waitFor(() => expect(screen.queryByRole("button", { name: /Re-parse statement/i })).not.toBeInTheDocument());
  });

  it("keeps the generic 409 message when the active run is an extract run", async () => {
    let started = false;
    mismatchApi(
      () => (started ? [F.mkRun({ id: "run-6", seq: 1, kind: "extract", state: "running", finished_at: null })] : []),
      () => {
        started = true;
        return F.err409(ApiError, BACKEND_409, { active_run_id: "run-6" })();
      },
    );
    render(<StatementDetailPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Re-parse statement/i }));
    await waitFor(() => expect(showToastMock).toHaveBeenCalledWith(GENERIC_409, "error"));
  });

  it("keeps the generic 409 message when the active run is not in the runs list", async () => {
    mismatchApi(() => [], () => F.err409(ApiError, BACKEND_409, { active_run_id: "run-unknown" })());
    render(<StatementDetailPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Re-parse statement/i }));
    await waitFor(() => expect(showToastMock).toHaveBeenCalledWith(GENERIC_409, "error"));
  });
});

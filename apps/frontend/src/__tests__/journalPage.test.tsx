import { render as R, screen as S, waitFor as W } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect as E, it, vi } from "vitest";
import JournalPage from "@/app/(main)/journal/page";
import { apiOperation } from "@/lib/api";
import * as X from "./helpers/shellTestFixtures";

const showToast = vi.fn();
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast }) }));
vi.mock("@/components/journal/JournalEntryForm", () => ({
  default: ({
    isOpen,
    onSuccess,
  }: {
    isOpen: boolean;
    onSuccess: () => void;
  }) => (isOpen ? <button onClick={onSuccess}>Mock Submit</button> : null),
}));
vi.mock("@/components/ui/ConfirmDialog", async () =>
  (await import("./helpers/shellTestFixtures")).confirmDlgMock(
    "Confirm",
    "Cancel",
    "void reason",
  ),
);
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const api = vi.mocked(apiOperation);

describe("JournalPage", () => {
  beforeEach(() => {
    api.mockReset();
    showToast.mockReset();
    vi.stubGlobal(
      "confirm",
      vi.fn(() => true),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it("retry, empty, create, details, filter", () =>
    X.runJournalEmptyAndDetails(api, () => R(<JournalPage />)));

  it("post/delete/void & cancel", async () => {
    const res = X.journalSampleRes();
    api
      .mockResolvedValueOnce(res)
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce(res)
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce(res)
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce({ items: [] });
    const v1 = R(<JournalPage />);
    await X.runJournalCrudActions(api);
    v1.unmount();

    api.mockResolvedValueOnce(res);
    R(<JournalPage />);
    await S.findByText("Draft Entry");
    for (const [b, c] of [
      ["Delete", "Delete Entry"],
      ["Void", "Void Entry"],
    ] as const) {
      X.clkBtn(b);
      X.clkBtn("Cancel");
      await W(() => E(S.queryByRole("button", { name: c })).toBeNull());
    }
  });

  it.each([
    ["Post", null, "post denied"],
    ["Delete", "Delete Entry", "delete denied"],
    ["Void", "Void Entry", "void denied"],
  ] as const)("error %s", async (a, c, msg) => {
    api
      .mockResolvedValueOnce(X.journalSampleRes())
      .mockRejectedValueOnce(new Error(msg));
    R(<JournalPage />);
    await S.findByText("Draft Entry");
    X.clkBtn(a);
    if (c) X.clkBtn(c);
    await W(() => E(S.getAllByText(msg).length).toBeGreaterThan(0));
  });
});
// AC-ledger.fe-accounts-journal.8-11

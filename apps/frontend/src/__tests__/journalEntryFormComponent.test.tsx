import { fireEvent as F, render as R, screen as S, waitFor as W } from "@testing-library/react";
import { beforeEach, describe, expect as E, it, vi } from "vitest";
import JournalEntryForm from "@/components/journal/JournalEntryForm";
import { apiOperation } from "@/lib/api";
import * as X from "./helpers/shellTestFixtures";

vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const api = vi.mocked(apiOperation), onClose = vi.fn(), onSuccess = vi.fn();

describe("JournalEntryForm", () => {
  beforeEach(() => { api.mockReset(); onClose.mockReset(); onSuccess.mockReset(); });

  it("balance, add/remove lines, closed/error", async () => {
    E(R(<JournalEntryForm isOpen={false} onClose={onClose} onSuccess={onSuccess} />).container.firstChild).toBeNull();
    api.mockRejectedValueOnce(new Error("accounts unavailable"));
    const v1 = R(<JournalEntryForm isOpen onClose={onClose} onSuccess={onSuccess} />);
    await W(() => E(S.getAllByRole("option", { name: "Select Account" })).toHaveLength(2)); v1.unmount();

    api.mockResolvedValueOnce({ items: X.JOURNAL_ACCOUNTS });
    const { container } = R(<JournalEntryForm isOpen onClose={onClose} onSuccess={onSuccess} />);
    await X.runJournalFormBalanceCheck(container);
  });

  it("multi-currency, post, errors", async () => {
    api.mockResolvedValueOnce({ items: X.JOURNAL_FX_ACCOUNTS }).mockResolvedValueOnce({ id: "je-fx" });
    const v1 = R(<JournalEntryForm isOpen onClose={onClose} onSuccess={onSuccess} />);
    await X.runJournalFormFxSubmit(api, v1.container); v1.unmount();
    await X.runJournalFormPostAndFail(api, () => R(<JournalEntryForm isOpen onClose={onClose} onSuccess={onSuccess} />));
  });
});
// AC-ledger.fe-accounts-journal.15-17

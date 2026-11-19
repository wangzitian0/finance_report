import { render as R, screen as S } from "@testing-library/react";
import { beforeEach, describe, expect as E, it, vi } from "vitest";
import OpeningBalanceModal from "@/components/accounts/OpeningBalanceModal";
import { apiOperation } from "@/lib/api";
import { REPORT_COVERAGE_QUERY_KEY } from "@/lib/sharedQueries";
import * as X from "./helpers/shellTestFixtures";

vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const api = vi.mocked(apiOperation), bp = () => ({ onClose: vi.fn(), onSuccess: vi.fn(), accounts: X.OPENING_ACCOUNTS });

describe("OpeningBalanceModal", () => {
  beforeEach(() => vi.clearAllMocks());

  it("prior-period, reopen, eligible", async () => {
    api.mockResolvedValueOnce({ id: "opening-entry" });
    const p = bp(), { rerender } = R(<OpeningBalanceModal {...p} isOpen />);
    await X.runOpeningBalDateChecks(api, rerender, (open) => <OpeningBalanceModal {...p} isOpen={open} />);
  });

  it("invalidates, empty, rejection", () =>
    X.runOpeningBalInvalidateAndErrors(api, REPORT_COVERAGE_QUERY_KEY, (props, wrapper) => R(<OpeningBalanceModal {...props} isOpen />, wrapper ? { wrapper } : undefined)));

  it.each(X.OPENING_SUGGEST_CASES)("suggests %s", (p, exp) => {
    R(<OpeningBalanceModal isOpen {...bp()} />); X.chgLbl("First report period starts", p); X.clkBtn(`Use ${exp}`); E(S.getByLabelText("As-of date *")).toHaveValue(exp);
  });

  it.each(X.OPENING_VALIDATION_CASES)("validates %#", async (p, d, a, msg) => {
    R(<OpeningBalanceModal isOpen {...bp()} />);
    if (p) X.chgLbl("First report period starts", p); X.chgLbl("As-of date *", d); if (a) X.chgLbl("Opening balance for Cash", a);
    X.clkBtn("Record opening balances"); await S.findByText(msg); E(api).not.toHaveBeenCalled();
  });
});

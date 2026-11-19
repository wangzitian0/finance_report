import { fireEvent as F, render as R, screen as S, waitFor as W } from "@testing-library/react";
import { beforeEach, describe, expect as E, it, vi } from "vitest";
import { AccountsPanel } from "@/components/settings/SettingsPanels";
import { apiOperation } from "@/lib/api";
import { accountsListVector } from "./fixtures/apiVectors";
import { createInvalidationProbe } from "./fixtures/invalidationProbe";
import * as X from "./helpers/shellTestFixtures";

const showToast = vi.fn();
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast }) }));
vi.mock("@/components/ui/ConfirmDialog", async () => (await import("./helpers/shellTestFixtures")).confirmDlgMock("Confirm Delete", "Cancel Delete", undefined, true));
vi.mock("@/components/accounts/AccountFormModal", async (o) => ({ ...(await o<typeof import("@/components/accounts/AccountFormModal")>()), ...(await import("./helpers/shellTestFixtures")).accountFormMock }));
vi.mock("@/components/accounts/OpeningBalanceModal", async () => (await import("./helpers/shellTestFixtures")).openingModalMock);
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const api = vi.mocked(apiOperation);

describe("AccountsPanel", () => {
  beforeEach(() => { api.mockReset(); showToast.mockReset(); });

  it("error retry, empty, vector filter", async () => {
    api.mockRejectedValue(new Error("accounts failed"));
    const v1 = R(<AccountsPanel />); await S.findByText("Failed to load accounts");
    const n = X.opCalls(api, X.OPS.ACC_LIST).length; X.clkBtn("Retry loading accounts");
    await W(() => E(X.opCalls(api, X.OPS.ACC_LIST).length).toBeGreaterThan(n)); v1.unmount();

    api.mockResolvedValueOnce(X.listOfAccounts([])); const v2 = R(<AccountsPanel />);
    await S.findByText("No accounts yet"); X.clkTxt("Create First Account"); X.hasTxts("Create Account Modal"); v2.unmount();

    api.mockResolvedValue(accountsListVector()); R(<AccountsPanel />);
    await S.findByText("Vector Checking"); X.clkBtn("LIABILITY"); X.noTxt("Vector Checking"); X.hasTxts("Vector Credit Card");
  });

  it("deletes, invalidates, cancels, errors", async () => {
    const probe = createInvalidationProbe("accounts.delete"); X.mockAccountsStd(api);
    const v1 = R(<AccountsPanel />, { wrapper: probe.wrapper }); await X.runAccountsDeleteFlow(api, showToast, probe); v1.unmount();
    X.mockAccountsStd(api, { [X.OPS.ACC_DEL]: () => { throw new Error("Cannot delete account with transactions"); } });
    R(<AccountsPanel />); await S.findByText("Cash"); F.click(S.getByTitle("Delete Account")); X.clkTxt("Confirm Delete");
    await W(() => E(showToast).toHaveBeenCalledWith("Failed to delete account: Cannot delete account with transactions", "error"));
  });

  it("modals, details, opening-balance nudge", async () => { X.mockAccountsNudgeRoutes(api); R(<AccountsPanel />); await X.runAccountsNudgeFlow(showToast); });
});
// AC-ledger.api-vectors.2 AC-ledger.fe-accounts-journal.1-7 AC-ledger.fe-accounts2.2-3 AC-meta.fe-app-shell.24

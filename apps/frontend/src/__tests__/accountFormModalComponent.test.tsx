import { useLayoutEffect } from "react";
import { fireEvent as F, render as R, screen as S } from "@testing-library/react";
import { beforeEach, describe, expect as E, it, vi } from "vitest";
import AccountFormModal from "@/components/accounts/AccountFormModal";
import { apiOperation } from "@/lib/api";
import * as X from "./helpers/shellTestFixtures";

vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const api = vi.mocked(apiOperation), onClose = vi.fn(), onSuccess = vi.fn();

describe("AccountFormModal", () => {
  beforeEach(() => { api.mockReset(); onClose.mockReset(); onSuccess.mockReset(); });

  it("creates, edits, validation/API errors", async () => {
    E(R(<AccountFormModal isOpen={false} onClose={onClose} onSuccess={onSuccess} />).container.firstChild).toBeNull();
    await X.runAccountFormCrudChecks(api, onClose, onSuccess, (editAccount) => R(<AccountFormModal isOpen onClose={onClose} onSuccess={onSuccess} editAccount={editAccount} />));
  });

  it("preserves first input when reopened", () => {
    function Host({ open, name, type }: { open: boolean; name: string; type: string }) {
      useLayoutEffect(() => { if (!open) return; X.chgPh("e.g., Cash on Hand", name); F.change(S.getAllByRole("combobox")[0], { target: { value: type } }); }, [open, name, type]);
      return <AccountFormModal isOpen={open} onClose={onClose} onSuccess={onSuccess} />;
    }
    return X.runAccountFormReopen(api, (open, name, type) => <Host open={open} name={name} type={type} />);
  });
});
// AC-ledger.fe-accounts-journal.12-14

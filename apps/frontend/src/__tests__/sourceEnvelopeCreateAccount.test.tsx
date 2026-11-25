import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import {
  SourceEnvelopeConfirmation,
  type EnvelopeDraft,
} from "@/components/statements/StatementReview";
const draft: EnvelopeDraft = {
  accountId: "",
  currency: "SGD",
  periodStart: "2026-10-01",
  periodEnd: "2026-10-31",
  openingBalance: "10000.00",
  closingBalance: "13500.00",
  rationale: "",
};
const S = screen,
  E = expect,
  env = (p: Partial<Parameters<typeof SourceEnvelopeConfirmation>[0]> = {}) =>
    render(
      <SourceEnvelopeConfirmation
        requiresEnvelopeConfirmation
        requiresOtherSourceReview={false}
        sourceMissingFacts={[]}
        missingFactLabels={{}}
        envelopeDraft={draft}
        onDraftChange={() => {}}
        custodyAccounts={[]}
        onConfirm={() => {}}
        isPending={false}
        {...p}
      />,
    );
it("AC-extraction.2477.1 AC-extraction.2832.3 inline create, filter, and field updates", () => {
  const c1 = vi.fn(),
    r1 = env({ onCreateAccount: c1, defaultAccountName: "DBS account" }),
    name = S.getByLabelText("New account name") as HTMLInputElement;
  E(name.value).toBe("DBS account");
  fireEvent.change(name, { target: { value: "DBS Savings" } });
  fireEvent.click(S.getByRole("button", { name: "Create account" }));
  E(c1).toHaveBeenCalledWith("DBS Savings");
  r1.unmount();
  const c2 = vi.fn(),
    r2 = env({ onCreateAccount: c2 }),
    btn = S.getByRole("button", {
      name: "Create account",
    }) as HTMLButtonElement;
  E(btn.disabled).toBe(true);
  fireEvent.click(btn);
  E(c2).not.toHaveBeenCalled();
  r2.unmount();
  const r3 = env({
    onCreateAccount: vi.fn(),
    custodyAccounts: [{ id: "a1", name: "DBS Savings", currency: "SGD" }],
  });
  E(S.queryByRole("button", { name: "Create account" })).toBeNull();
  r3.unmount();
  const c4 = vi.fn(),
    r4 = env({
      onCreateAccount: c4,
      envelopeDraft: { ...draft, currency: "USD" },
      custodyAccounts: [{ id: "sgd-1", name: "DBS Savings", currency: "SGD" }],
      defaultAccountName: "Chase Checking",
    });
  E(
    Array.from(
      (S.getByLabelText("Custody account") as HTMLSelectElement).options,
    ).map((o) => o.text),
  ).toEqual(["Select an asset account"]);
  E(S.getByText(/No USD asset account exists yet/i)).toBeTruthy();
  fireEvent.click(S.getByRole("button", { name: "Create account" }));
  E(c4).toHaveBeenCalledWith("Chase Checking");
  r4.unmount();
  for (const [l, k, v] of [
    ["Custody account", "accountId", "a1"],
    ["Statement currency", "currency", "USD"],
    ["Period start", "periodStart", "2026-09-01"],
    ["Period end", "periodEnd", "2026-09-30"],
    ["Opening balance", "openingBalance", "1.00"],
    ["Closing balance", "closingBalance", "2.00"],
    ["Why are these facts confirmed\\?", "rationale", "Checked"],
  ] as const) {
    const out: EnvelopeDraft[] = [],
      r = env({
        custodyAccounts: [{ id: "a1", name: "DBS Savings", currency: "SGD" }],
        onDraftChange: (u) => out.push(u(draft)),
      });
    fireEvent.change(S.getByLabelText(new RegExp(`^${l}`)), {
      target: { value: v },
    });
    E(out).toEqual([{ ...draft, [k]: v }]);
    r.unmount();
  }
});

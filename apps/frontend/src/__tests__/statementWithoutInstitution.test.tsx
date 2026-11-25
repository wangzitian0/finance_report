import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import {
  SourceEnvelopeConfirmation,
  type EnvelopeDraft,
} from "@/components/statements/StatementReview";
import {
  INSTITUTION_NOT_STATED,
  institutionLabel,
  statementDisplayTitle,
} from "@/lib/statusLabels";

const draft: EnvelopeDraft = {
  accountId: "a1",
  currency: "SGD",
  periodStart: "2026-03-01",
  periodEnd: "2026-03-31",
  openingBalance: "1000.00",
  closingBalance: "1720.00",
  rationale: "Read on the paper statement.",
};
const accounts = [{ id: "a1", name: "Everyday", currency: "SGD" }];
const form = (
  sourceMissingFacts: string[],
  envelopeDraft: EnvelopeDraft,
  onDraftChange: (u: (p: EnvelopeDraft) => EnvelopeDraft) => void = () => {},
) =>
  render(
    <SourceEnvelopeConfirmation
      requiresEnvelopeConfirmation
      requiresOtherSourceReview={false}
      sourceMissingFacts={sourceMissingFacts}
      missingFactLabels={{ institution: "institution" }}
      envelopeDraft={envelopeDraft}
      onDraftChange={onDraftChange}
      custodyAccounts={accounts}
      onConfirm={() => {}}
      isPending={false}
    />,
  );
const confirmButton = () =>
  screen.getByRole("button", {
    name: "Confirm statement details",
  }) as HTMLButtonElement;

it("shows one fixed text for a statement without an institution and keeps a stated institution (#3167)", () => {
  expect([
    institutionLabel(null),
    institutionLabel(undefined),
    institutionLabel("  "),
    institutionLabel("ACME"),
  ]).toEqual([
    INSTITUTION_NOT_STATED,
    INSTITUTION_NOT_STATED,
    INSTITUTION_NOT_STATED,
    "ACME",
  ]);
  expect(INSTITUTION_NOT_STATED).toBe("Institution not stated");
  expect(
    statementDisplayTitle({
      institution: null,
      period_start: "2026-03-01",
      period_end: "2026-03-31",
    }),
  ).toBe("Institution not stated (2026-03-01 – 2026-03-31)");
});

it("requires the institution in the confirmation form when the source misses it (#3167)", () => {
  const out: EnvelopeDraft[] = [];
  const blank = form(["institution"], draft, (u) => out.push(u(draft)));
  const input = screen.getByLabelText("Institution") as HTMLInputElement;
  expect([input.required, input.maxLength, confirmButton().disabled]).toEqual([
    true,
    100,
    true,
  ]);
  expect(
    screen.getByText(/This source did not declare institution\./),
  ).toBeTruthy();
  fireEvent.change(input, { target: { value: "Reviewed Bank" } });
  expect(out).toEqual([{ ...draft, institution: "Reviewed Bank" }]);
  blank.unmount();

  const spaces = form(["institution"], { ...draft, institution: "   " });
  expect(confirmButton().disabled).toBe(true);
  spaces.unmount();

  const stated = form(["institution"], {
    ...draft,
    institution: "Reviewed Bank",
  });
  expect(confirmButton().disabled).toBe(false);
  stated.unmount();
});

it("shows no institution input when the source states the institution (#3167)", () => {
  form(["period"], draft);
  expect(screen.queryByLabelText("Institution")).toBeNull();
  expect(confirmButton().disabled).toBe(false);
});

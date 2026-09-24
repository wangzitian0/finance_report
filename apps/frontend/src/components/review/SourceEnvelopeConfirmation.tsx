"use client";

import React from "react";

export interface EnvelopeDraft {
  accountId: string;
  currency: string;
  periodStart: string;
  periodEnd: string;
  openingBalance: string;
  closingBalance: string;
  rationale: string;
}

export interface CustodyAccount {
  id: string;
  name: string;
  currency: string;
  type?: string;
  is_active?: boolean;
}

interface SourceEnvelopeConfirmationProps {
  requiresEnvelopeConfirmation: boolean;
  requiresOtherSourceReview: boolean;
  sourceMissingFacts: string[];
  missingFactLabels: Record<string, string>;
  envelopeDraft: EnvelopeDraft;
  onDraftChange: (updater: (prev: EnvelopeDraft) => EnvelopeDraft) => void;
  custodyAccounts: CustodyAccount[];
  onConfirm: () => void;
  isPending: boolean;
  reviewedEnvelope?: unknown | null;
}

export function SourceEnvelopeConfirmation({
  requiresEnvelopeConfirmation,
  requiresOtherSourceReview,
  sourceMissingFacts,
  missingFactLabels,
  envelopeDraft,
  onDraftChange,
  custodyAccounts,
  onConfirm,
  isPending,
  reviewedEnvelope,
}: SourceEnvelopeConfirmationProps) {
  const isComplete = Boolean(
    envelopeDraft.accountId &&
      envelopeDraft.currency &&
      envelopeDraft.periodStart &&
      envelopeDraft.periodEnd &&
      envelopeDraft.openingBalance &&
      envelopeDraft.closingBalance &&
      envelopeDraft.rationale.trim(),
  );

  return (
    <>
      {requiresEnvelopeConfirmation && (
        <section
          className="mb-4 rounded-lg border border-[var(--warning)]/40 bg-[var(--warning-muted)] p-4"
          aria-labelledby="source-envelope-heading"
        >
          <div className="mb-3">
            <h2 id="source-envelope-heading" className="font-semibold">
              {sourceMissingFacts.length
                ? "Confirm missing source facts"
                : "Confirm source facts"}
            </h2>
            <p className="mt-1 text-sm text-muted">
              {sourceMissingFacts.length ? (
                <>
                  This source did not declare{" "}
                  {sourceMissingFacts
                    .map((fact) => missingFactLabels[fact] || fact)
                    .join(", ")}
                  . Confirm only facts you can support from the original
                  document or export.
                </>
              ) : (
                <>
                  This statement needs your confirmation before it can be used.
                  Check the transaction list, account, dates, and balances
                  against the original document. Known source facts must remain
                  unchanged.
                </>
              )}
            </p>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <label className="text-sm font-medium" htmlFor="custody-account">
              Custody account
              <select
                id="custody-account"
                value={envelopeDraft.accountId}
                onChange={(event) =>
                  onDraftChange((current) => ({
                    ...current,
                    accountId: event.target.value,
                  }))
                }
                className="input mt-1 w-full"
              >
                <option value="">Select an asset account</option>
                {custodyAccounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.name} ({account.currency})
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm font-medium" htmlFor="statement-currency">
              Statement currency
              <input
                id="statement-currency"
                value={envelopeDraft.currency}
                onChange={(event) =>
                  onDraftChange((current) => ({
                    ...current,
                    currency: event.target.value.toUpperCase(),
                  }))
                }
                className="input mt-1 w-full"
                maxLength={3}
                placeholder="SGD"
              />
            </label>
            <label className="text-sm font-medium" htmlFor="period-start">
              Period start
              <input
                id="period-start"
                type="date"
                value={envelopeDraft.periodStart}
                onChange={(event) =>
                  onDraftChange((current) => ({
                    ...current,
                    periodStart: event.target.value,
                  }))
                }
                className="input mt-1 w-full"
              />
            </label>
            <label className="text-sm font-medium" htmlFor="period-end">
              Period end
              <input
                id="period-end"
                type="date"
                value={envelopeDraft.periodEnd}
                onChange={(event) =>
                  onDraftChange((current) => ({
                    ...current,
                    periodEnd: event.target.value,
                  }))
                }
                className="input mt-1 w-full"
              />
            </label>
            <label className="text-sm font-medium" htmlFor="opening-balance">
              Opening balance
              <input
                id="opening-balance"
                inputMode="decimal"
                value={envelopeDraft.openingBalance}
                onChange={(event) =>
                  onDraftChange((current) => ({
                    ...current,
                    openingBalance: event.target.value,
                  }))
                }
                className="input mt-1 w-full"
              />
            </label>
            <label className="text-sm font-medium" htmlFor="closing-balance">
              Closing balance
              <input
                id="closing-balance"
                inputMode="decimal"
                value={envelopeDraft.closingBalance}
                onChange={(event) =>
                  onDraftChange((current) => ({
                    ...current,
                    closingBalance: event.target.value,
                  }))
                }
                className="input mt-1 w-full"
              />
            </label>
          </div>
          <label
            className="mt-3 block text-sm font-medium"
            htmlFor="envelope-rationale"
          >
            Why are these facts confirmed?
            <textarea
              id="envelope-rationale"
              value={envelopeDraft.rationale}
              onChange={(event) =>
                onDraftChange((current) => ({
                  ...current,
                  rationale: event.target.value,
                }))
              }
              className="input mt-1 min-h-20 w-full"
              placeholder="State the page, export header, or other source evidence used."
            />
          </label>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isPending || !isComplete}
            className="btn-primary mt-3 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isPending ? "Confirming..." : "Confirm source envelope"}
          </button>
        </section>
      )}

      {requiresOtherSourceReview && (
        <section
          className="mb-4 rounded-lg border border-[var(--warning)]/40 bg-[var(--warning-muted)] p-4"
          aria-labelledby="source-review-required-heading"
        >
          <h2 id="source-review-required-heading" className="font-semibold">
            Source review required
          </h2>
          <p className="mt-1 text-sm text-muted">
            {sourceMissingFacts
              .map((fact) => missingFactLabels[fact] || fact)
              .join(", ")}{" "}
            cannot be confirmed by a cash statement envelope. Re-parse the
            source or use the review path that owns those facts.
          </p>
        </section>
      )}

      {Boolean(reviewedEnvelope) && (
        <p className="mb-4 rounded-md border border-[var(--success)]/30 bg-[var(--success-muted)] p-3 text-sm">
          Source envelope confirmed and anchored to the current extraction
          result.
        </p>
      )}
    </>
  );
}

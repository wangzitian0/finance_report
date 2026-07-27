"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";

import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { useToast } from "@/components/ui/Toast";
import { ApiError, apiOperation } from "@/lib/api-client";
import { track, ANALYTICS_EVENTS } from "@/lib/analytics";
import { confirmStatementReviewEnvelope } from "@/lib/statementReviewApi";
import type { MoneyValue } from "@/lib/types";
import type { Schemas } from "@/lib/api-schema";

import { FlowStepBanner } from "@/components/workflow/FlowStepBanner";
import { BalanceIndicator } from "@/components/review/BalanceIndicator";
import { PdfPreviewPane } from "@/components/review/PdfPreviewPane";
import { ReviewActionBar } from "@/components/review/ReviewActionBar";
import {
  TransactionTable,
  Transaction,
} from "@/components/review/TransactionTable";
import { ConflictResolutionDialog } from "@/components/review/ConflictResolutionDialog";
import {
  ATTENTION_RETURN_HREF,
  ATTENTION_RETURN_LABEL,
  isAttentionOrigin,
  withAttentionSource,
} from "@/lib/attentionNavigation";

interface BalanceValidationResult {
  opening_balance: string;
  // null when the statement has no declared closing balance (#1390).
  closing_balance: string | null;
  calculated_closing: string;
  opening_delta: string;
  closing_delta: string;
  opening_match: boolean;
  closing_match: boolean;
  validated_at: string;
}

interface StatementReview {
  id: string;
  account_id: string | null;
  original_filename: string;
  institution: string;
  account_last4: string | null;
  currency: string | null;
  period_start: string | null;
  period_end: string | null;
  opening_balance: MoneyValue | null;
  closing_balance: MoneyValue | null;
  status: string;
  stage1_status: string | null;
  balance_validation_result: BalanceValidationResult | null;
  pdf_url: string | null;
  transactions: Transaction[];
  source_result_digest?: string | null;
  source_missing_facts?: string[];
  source_envelope_reviewable?: boolean;
  reviewed_envelope?: {
    id: string;
    source_result_digest: string;
    account_id: string;
    currency: string;
    period_start: string;
    period_end: string;
    opening_balance: MoneyValue;
    closing_balance: MoneyValue;
    rationale: string;
    review_trace_record_id: string;
    created_at: string;
  } | null;
}

interface CustodyAccount {
  id: string;
  name: string;
  type: "ASSET";
  currency: string;
  is_active: boolean;
}

interface EnvelopeDraft {
  accountId: string;
  currency: string;
  periodStart: string;
  periodEnd: string;
  openingBalance: string;
  closingBalance: string;
  rationale: string;
}

interface ConflictCandidate {
  id: string;
  description: string;
  txn_date: string;
  amount: MoneyValue;
}

interface ReviewConflicts {
  duplicates: ConflictCandidate[];
  transfer_pairs: ConflictCandidate[];
  // #962: persisted resolution marker, so the blocked state survives a refresh.
  resolved?: boolean;
}

type Stage1ApprovalResponse = Schemas["Stage1ApprovalResponse"];

export default function StatementReviewPage() {
  const { showToast } = useToast();
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const statementId = params.id as string;
  const fromAttention = isAttentionOrigin(searchParams);
  const returnHref = fromAttention ? ATTENTION_RETURN_HREF : "/statements";
  const returnLabel = fromAttention
    ? ATTENTION_RETURN_LABEL
    : "Back to Statements";
  const statementReviewHref = (id: string) =>
    fromAttention
      ? withAttentionSource(`/statements/${id}/review`)
      : `/statements/${id}/review`;

  const [approveDialogOpen, setApproveDialogOpen] = useState(false);
  const [rejectDialogOpen, setRejectDialogOpen] = useState(false);
  const [conflictDialogOpen, setConflictDialogOpen] = useState(false);
  const [conflictsResolved, setConflictsResolved] = useState(false);
  const [envelopeDraft, setEnvelopeDraft] = useState<EnvelopeDraft>({
    accountId: "",
    currency: "",
    periodStart: "",
    periodEnd: "",
    openingBalance: "",
    closingBalance: "",
    rationale: "",
  });
  const queryClient = useQueryClient();

  // Queries
  const {
    data,
    isLoading: loading,
    error,
    refetch,
  } = useQuery({
    queryKey: ["statement-review", statementId],
    queryFn: () =>
      apiOperation(
        "get_statement_for_review_statements__statement_id__review_get",
        {
          path: { statement_id: statementId },
        },
      ),
  });

  const { data: pendingStatementsData } = useQuery({
    queryKey: ["pending-statements"],
    queryFn: () =>
      apiOperation("list_pending_review_statements_pending_review_get"),
  });

  const { data: conflicts } = useQuery({
    queryKey: ["statement-conflicts", statementId],
    queryFn: () =>
      apiOperation("get_review_conflicts_review_conflicts__statement_id__get", {
        path: { statement_id: statementId },
      }),
  });

  const pendingStatements = pendingStatementsData?.items || [];
  const duplicateCandidates = conflicts?.duplicates || [];
  const transferPairCandidates = conflicts?.transfer_pairs || [];
  const sourceMissingFacts = data?.source_missing_facts || [];
  const sourceEnvelopeReviewable = Boolean(data?.source_envelope_reviewable);
  const requiresEnvelopeConfirmation =
    sourceEnvelopeReviewable &&
    sourceMissingFacts.length > 0 &&
    !data?.reviewed_envelope;
  const requiresOtherSourceReview =
    !sourceEnvelopeReviewable &&
    sourceMissingFacts.length > 0 &&
    !data?.reviewed_envelope;

  const { data: custodyAccountsData } = useQuery({
    queryKey: ["statement-review-custody-accounts", statementId],
    queryFn: () =>
      apiOperation("list_accounts_accounts_get", {
        query: { account_type: "ASSET", is_active: true },
      }),
    enabled: requiresEnvelopeConfirmation,
  });

  // Mutations
  const approveMutation = useMutation({
    mutationFn: () =>
      apiOperation(
        "approve_statement_stage1_statements__statement_id__review_approve_post",
        {
          path: { statement_id: statementId },
          body: { create_account_if_missing: !data?.account_id },
        },
      ),
    onSuccess: (result) => {
      const createdCount = result.journal_entries_created ?? 0;
      // EPIC-022 AC22.18.3 (#1109): instrument the Stage-1 review approval.
      // statement_id is a non-PII opaque identifier.
      track(ANALYTICS_EVENTS.REVIEW_APPROVED, { statement_id: statementId });
      showToast(
        `Statement approved. ${createdCount} journal entries posted.`,
        "success",
      );
      setApproveDialogOpen(false);
      router.push(
        fromAttention
          ? ATTENTION_RETURN_HREF
          : `/statements/${statementId}?approved=1&entriesCreated=${createdCount}`,
      );
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) {
        setApproveDialogOpen(false);
        showToast(
          "Economic classification needs review before entries can be posted.",
          "error",
        );
        void refetch();
        return;
      }
      showToast(
        err instanceof Error ? err.message : "Failed to approve",
        "error",
      );
    },
  });

  const envelopeMutation = useMutation({
    mutationFn: () => {
      if (!data?.source_result_digest) {
        return Promise.reject(
          new Error(
            "The source result is unavailable. Re-parse the statement before confirming it.",
          ),
        );
      }
      return confirmStatementReviewEnvelope(statementId, {
        source_result_digest: data.source_result_digest,
        account_id: envelopeDraft.accountId,
        currency: envelopeDraft.currency,
        period_start: envelopeDraft.periodStart,
        period_end: envelopeDraft.periodEnd,
        opening_balance: envelopeDraft.openingBalance,
        closing_balance: envelopeDraft.closingBalance,
        rationale: envelopeDraft.rationale,
      });
    },
    onSuccess: () => {
      showToast(
        "Source envelope confirmed. You can now continue the review.",
        "success",
      );
      queryClient.invalidateQueries({
        queryKey: ["statement-review", statementId],
      });
    },
    onError: (err) =>
      showToast(
        err instanceof Error ? err.message : "Failed to confirm source facts",
        "error",
      ),
  });

  const rejectMutation = useMutation({
    mutationFn: (notes?: string) =>
      apiOperation(
        "reject_statement_stage1_statements__statement_id__review_reject_post",
        {
          path: { statement_id: statementId },
          body: { notes: notes || null },
        },
      ),
    onSuccess: () => {
      showToast("Statement rejected", "success");
      setRejectDialogOpen(false);
      router.push(fromAttention ? ATTENTION_RETURN_HREF : "/statements");
    },
    onError: (err) =>
      showToast(
        err instanceof Error ? err.message : "Failed to reject",
        "error",
      ),
  });

  // #962 / AC16.34.1: resolve the duplicate/transfer-pair candidates so a
  // legitimately-conflicting statement can be approved instead of being stuck.
  const resolveConflictsMutation = useMutation({
    mutationFn: (action: "confirm_distinct" | "link_transfer") =>
      apiOperation(
        "resolve_review_conflicts_review_conflicts__statement_id__resolve_post",
        {
          path: { statement_id: statementId },
          body: { action },
        },
      ),
    onSuccess: () => {
      showToast("Conflicts resolved", "success");
      setConflictsResolved(true);
      setConflictDialogOpen(false);
      // Refetch so the persisted `resolved` marker drives the blocked state
      // on subsequent renders, not just this session's local flag.
      queryClient.invalidateQueries({
        queryKey: ["statement-conflicts", statementId],
      });
    },
    onError: (err) =>
      showToast(
        err instanceof Error ? err.message : "Failed to resolve conflicts",
        "error",
      ),
  });

  // EPIC-022 AC22.5.2: re-parse in place when a balance mismatch blocks approval,
  // instead of forcing a reject -> back-to-detail -> retry detour.
  const reparseMutation = useMutation({
    mutationFn: () =>
      apiOperation(
        "retry_statement_parsing_statements__statement_id__retry_post",
        {
          path: { statement_id: statementId },
        },
      ),
    onSuccess: () => {
      showToast("Re-parsing started", "success");
      router.push(
        fromAttention ? ATTENTION_RETURN_HREF : `/statements/${statementId}`,
      );
    },
    onError: (err) =>
      showToast(
        err instanceof Error ? err.message : "Failed to re-parse",
        "error",
      ),
  });

  useEffect(() => {
    // Don't reopen the dialog for candidates the reviewer already resolved
    // (persisted marker) — only when there is something still to resolve.
    if (
      !conflicts?.resolved &&
      (duplicateCandidates.length || transferPairCandidates.length)
    ) {
      setConflictDialogOpen(true);
    }
  }, [
    duplicateCandidates.length,
    transferPairCandidates.length,
    conflicts?.resolved,
  ]);

  useEffect(() => {
    if (!data || !requiresEnvelopeConfirmation) return;
    setEnvelopeDraft({
      accountId: data.account_id || "",
      currency: data.currency || "",
      periodStart: data.period_start || "",
      periodEnd: data.period_end || "",
      openingBalance: data.opening_balance?.toString() || "",
      closingBalance: data.closing_balance?.toString() || "",
      rationale: "",
    });
  }, [data, requiresEnvelopeConfirmation]);

  if (loading) {
    return (
      <div className="p-6">
        <div className="card p-8 text-center text-muted">
          <div className="inline-block w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin mb-2" />
          <p className="text-sm">Loading review data...</p>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="p-6">
        <div className="card p-12 text-center max-w-md mx-auto">
          {error ? (
            <>
              <div className="w-12 h-12 bg-[var(--error-muted)] text-[var(--error)] rounded-full flex items-center justify-center mx-auto mb-4">
                <span className="text-xl font-bold">!</span>
              </div>
              <h2 className="text-lg font-medium mb-2">
                Failed to load statement
              </h2>
              <p className="text-muted mb-6">
                {error instanceof Error ? error.message : "Unknown error"}
              </p>
              <div className="flex gap-3 justify-center">
                <button
                  type="button"
                  onClick={() => refetch()}
                  className="btn-primary"
                >
                  Retry
                </button>
                <Link href={returnHref} className="btn-secondary">
                  {returnLabel}
                </Link>
              </div>
            </>
          ) : (
            <>
              <p className="text-muted mb-6">Statement not found</p>
              <Link href={returnHref} className="btn-primary">
                {returnLabel}
              </Link>
            </>
          )}
        </div>
      </div>
    );
  }

  const balanceValid = Boolean(
    data.balance_validation_result?.opening_match &&
    data.balance_validation_result?.closing_match,
  );
  // Honor the server-persisted resolution marker so a refresh (or a resolution
  // from another tab/session) keeps approval unblocked, not just this session's
  // local flag (#962 review follow-up).
  const conflictsAreResolved =
    conflictsResolved || Boolean(conflicts?.resolved);
  const hasUnresolvedConflicts =
    !conflictsAreResolved &&
    (duplicateCandidates.length > 0 || transferPairCandidates.length > 0);
  const missingFactLabels: Record<string, string> = {
    statement_currency: "statement currency",
    period: "statement period",
    balances: "opening and closing balances",
    transaction_currency: "transaction currency",
  };
  const approvalBlockedReason = requiresEnvelopeConfirmation
    ? "Confirm the missing source facts before approving this statement."
    : requiresOtherSourceReview
      ? "This source has facts that a cash statement envelope cannot confirm."
      : hasUnresolvedConflicts
        ? "Resolve duplicate and transfer-pair candidates before approval"
        : null;

  return (
    <div className="flex min-h-[calc(100dvh-2rem)] w-full max-w-full min-w-0 flex-col overflow-x-hidden p-4 md:p-6 2xl:h-[calc(100dvh-2rem)]">
      <div className="mb-4 flex min-w-0 max-w-full flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <Link
          href={returnHref}
          className="flex min-w-0 items-center gap-1 text-sm text-muted hover:text-[var(--foreground)]"
        >
          <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          <span className="truncate">{returnLabel}</span>
        </Link>

        <div className="flex min-w-0 max-w-full items-center gap-2 overflow-x-auto">
          {(() => {
            const currentIndex = pendingStatements.findIndex(
              (s) => s.id === statementId,
            );
            const prevId =
              currentIndex > 0 ? pendingStatements[currentIndex - 1].id : null;
            const nextId =
              currentIndex >= 0 && currentIndex < pendingStatements.length - 1
                ? pendingStatements[currentIndex + 1].id
                : null;

            return (
              <>
                <button
                  onClick={() =>
                    prevId && router.push(statementReviewHref(prevId))
                  }
                  disabled={!prevId}
                  className="btn-ghost btn-sm disabled:opacity-30"
                  title="Previous pending statement"
                >
                  ← Prev
                </button>
                <span className="text-xs text-muted">
                  {currentIndex + 1} / {pendingStatements.length}
                </span>
                <button
                  onClick={() =>
                    nextId && router.push(statementReviewHref(nextId))
                  }
                  disabled={!nextId}
                  className="btn-ghost btn-sm disabled:opacity-30"
                  title="Next pending statement"
                >
                  Next →
                </button>
              </>
            );
          })()}
        </div>
      </div>

      <div className="mb-4">
        <FlowStepBanner current="review" />
      </div>

      <div className="page-header mb-4 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <h1 className="page-title">{data.original_filename}</h1>
          <p className="page-description">
            {data.institution} • {data.currency || "—"} •{" "}
            {data.period_start || "?"} to {data.period_end || "?"}
          </p>
        </div>
        <ReviewActionBar
          onApprove={() => setApproveDialogOpen(true)}
          onReject={() => setRejectDialogOpen(true)}
          actionLoading={approveMutation.isPending || rejectMutation.isPending}
          balanceValid={balanceValid}
          approvalBlockedReason={approvalBlockedReason}
          onResolveConflicts={
            hasUnresolvedConflicts
              ? () => setConflictDialogOpen(true)
              : undefined
          }
          onReparse={() => reparseMutation.mutate()}
          reparsePending={reparseMutation.isPending}
        />
      </div>

      <BalanceIndicator
        openingBalance={data.opening_balance}
        closingBalance={data.closing_balance}
        validationResult={data.balance_validation_result ?? null}
        currency={data.currency || "SGD"}
      />

      {requiresEnvelopeConfirmation && (
        <section
          className="mb-4 rounded-lg border border-[var(--warning)]/40 bg-[var(--warning-muted)] p-4"
          aria-labelledby="source-envelope-heading"
        >
          <div className="mb-3">
            <h2 id="source-envelope-heading" className="font-semibold">
              Confirm missing source facts
            </h2>
            <p className="mt-1 text-sm text-muted">
              This source did not declare{" "}
              {sourceMissingFacts
                .map((fact) => missingFactLabels[fact] || fact)
                .join(", ")}
              . Confirm only facts you can support from the original document or
              export.
            </p>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <label className="text-sm font-medium" htmlFor="custody-account">
              Custody account
              <select
                id="custody-account"
                value={envelopeDraft.accountId}
                onChange={(event) =>
                  setEnvelopeDraft((current) => ({
                    ...current,
                    accountId: event.target.value,
                  }))
                }
                className="input mt-1 w-full"
              >
                <option value="">Select an asset account</option>
                {(custodyAccountsData?.items || []).map((account) => (
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
                  setEnvelopeDraft((current) => ({
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
                  setEnvelopeDraft((current) => ({
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
                  setEnvelopeDraft((current) => ({
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
                  setEnvelopeDraft((current) => ({
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
                  setEnvelopeDraft((current) => ({
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
                setEnvelopeDraft((current) => ({
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
            onClick={() => envelopeMutation.mutate()}
            disabled={
              envelopeMutation.isPending ||
              !envelopeDraft.accountId ||
              !envelopeDraft.currency ||
              !envelopeDraft.periodStart ||
              !envelopeDraft.periodEnd ||
              !envelopeDraft.openingBalance ||
              !envelopeDraft.closingBalance ||
              !envelopeDraft.rationale.trim()
            }
            className="btn-primary mt-3 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {envelopeMutation.isPending
              ? "Confirming..."
              : "Confirm source envelope"}
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

      {data.reviewed_envelope && (
        <p className="mb-4 rounded-md border border-[var(--success)]/30 bg-[var(--success-muted)] p-3 text-sm">
          Source envelope confirmed and anchored to the current extraction
          result.
        </p>
      )}

      <div className="grid min-w-0 flex-1 grid-cols-1 gap-4 2xl:min-h-0 2xl:grid-cols-2">
        <PdfPreviewPane
          statementId={statementId}
          hasDocument={Boolean(data.original_filename)}
        />

        <TransactionTable
          transactions={data.transactions ?? []}
          currency={data.currency || "SGD"}
        />
      </div>

      <ConflictResolutionDialog
        isOpen={conflictDialogOpen}
        onClose={() => setConflictDialogOpen(false)}
        duplicateCandidates={duplicateCandidates}
        transferPairCandidates={transferPairCandidates}
        onResolve={(action) => resolveConflictsMutation.mutate(action)}
        isResolving={resolveConflictsMutation.isPending}
      />

      <ConfirmDialog
        isOpen={approveDialogOpen}
        onCancel={() =>
          !approveMutation.isPending && setApproveDialogOpen(false)
        }
        onConfirm={() => approveMutation.mutate()}
        title="Approve Statement"
        message={
          data.account_id
            ? "This will approve the statement with balance validation. Proceed?"
            : "This will create and map an asset account for this statement, then approve it with balance validation. Proceed?"
        }
        confirmLabel="Approve"
        loading={approveMutation.isPending}
      />

      <ConfirmDialog
        isOpen={rejectDialogOpen}
        onCancel={() => !rejectMutation.isPending && setRejectDialogOpen(false)}
        onConfirm={(reason) => rejectMutation.mutate(reason)}
        title="Reject Statement"
        message="Parsed transactions can't be edited. To fix a mis-parse, reject this statement and re-parse it (Retry Parse) from the statement page. This will mark the statement as rejected."
        confirmLabel="Reject"
        confirmVariant="danger"
        input={{
          label: "Rejection Reason (optional)",
          placeholder: "Enter reason for rejection...",
        }}
        loading={rejectMutation.isPending}
      />
    </div>
  );
}

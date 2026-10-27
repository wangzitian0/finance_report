"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/ui/Toast";
import { LoadingState } from "@/components/ui";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { FlowStepBanner } from "@/components/workflow/WorkflowNotifications";
import { ApiError, apiOperation } from "@/lib/api-client";
import { track, ANALYTICS_EVENTS } from "@/lib/analytics";
import { confirmStatementReviewEnvelope } from "@/lib/statementReviewApi";
import { ATTENTION_RETURN_HREF, ATTENTION_RETURN_LABEL, NEEDS_YOU_HREF, isAttentionOrigin, withAttentionSource } from "@/lib/attentionNavigation";
import { BankStatement, BrokerageImportResponse, normalizeBankStatement } from "@/lib/types";
import { PARSING_POLL_MS, canImportBrokerageStatement, currencyCodeOrDash } from "@/lib/statusLabels";
import { formatPeriod } from "@/lib/date";
import { invalidateLedgerDerivedQueries, invalidatePortfolioQueries } from "@/lib/queryClient";
import { PdfPreviewPane, hasInlinePreview } from "@/components/review/PdfPreviewPane";
import { LowConfidenceReviewModal } from "@/components/review/LowConfidenceReviewModal";
import {
  BalanceIndicator,
  BrokerageImportResultBanner,
  ConflictResolutionDialog,
  ReviewActionBar,
  SourceEnvelopeConfirmation,
  StatementHeader,
  TransactionTable,
  type EnvelopeDraft,
  type Transaction,
} from "@/components/review/TransactionTable";

const PARSING_TIMEOUT_MS = 5 * 60 * 1000;
const MISSING_FACT_LABELS: Record<string, string> = { statement_currency: "statement currency", period: "statement period", balances: "opening and closing balances", transaction_currency: "transaction currency" };

export default function StatementDetailPage() {
  const { showToast } = useToast();
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const statementId = params.id as string;
  const fromAttention = isAttentionOrigin(searchParams);
  const returnHref = fromAttention ? ATTENTION_RETURN_HREF : "/upload";
  const returnLabel = fromAttention ? ATTENTION_RETURN_LABEL : "Back to Upload";
  const statementHref = (id: string) => (fromAttention ? withAttentionSource(`/statements/${id}`) : `/statements/${id}`);

  const [statement, setStatement] = useState<BankStatement | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retryLoading, setRetryLoading] = useState(false);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [polling, setPolling] = useState(false);
  const [pollingStoppedReason, setPollingStoppedReason] = useState<string | null>(null);
  const [parsingStartTime, setParsingStartTime] = useState<number | null>(null);
  const [importResult, setImportResult] = useState<BrokerageImportResponse | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [importLoading, setImportLoading] = useState(false);
  const [approvedEntries, setApprovedEntries] = useState<number | null>(null);
  const [approveDialogOpen, setApproveDialogOpen] = useState(false);
  const [rejectDialogOpen, setRejectDialogOpen] = useState(false);
  const [conflictDialogOpen, setConflictDialogOpen] = useState(false);
  const [conflictsResolved, setConflictsResolved] = useState(false);
  const [economicReviewRequired, setEconomicReviewRequired] = useState(false);
  const [reviewingTxn, setReviewingTxn] = useState<Transaction | null>(null);
  const [envelopeDraft, setEnvelopeDraft] = useState<EnvelopeDraft>({
    accountId: "", currency: "", periodStart: "", periodEnd: "", openingBalance: "", closingBalance: "", rationale: "",
  });
  const mountedRef = useRef(false);
  const pollingRef = useRef(false);
  const consecutiveErrorsRef = useRef(0);
  const requestSequenceRef = useRef(0);
  const activeRequestRef = useRef<{ controller: AbortController; requestId: number } | null>(null);
  const approvedNow = approvedEntries !== null && statement?.status === "approved";
  const isParsed = statement?.status === "parsed";

  const updatePolling = useCallback((enabled: boolean) => {
    pollingRef.current = enabled;
    setPolling(enabled);
  }, []);

  const fetchStatement = useCallback(async ({ supersede = false }: { supersede?: boolean } = {}) => {
    if (!mountedRef.current) return;
    if (activeRequestRef.current) {
      if (!supersede) return;
      activeRequestRef.current.controller.abort();
      activeRequestRef.current = null;
    }
    const controller = new AbortController();
    const requestId = ++requestSequenceRef.current;
    activeRequestRef.current = { controller, requestId };
    const ownsResult = () => mountedRef.current && !controller.signal.aborted && activeRequestRef.current?.requestId === requestId;

    try {
      const data = await apiOperation("get_statement_statements__statement_id__get", { path: { statement_id: statementId }, signal: controller.signal });
      if (!ownsResult()) return;
      if (!data) {
        setStatement(null);
        setError(null);
        updatePolling(false);
        return;
      }
      setStatement(normalizeBankStatement(data));
      setError(null);
      consecutiveErrorsRef.current = 0;
      if (data.status === "parsing") {
        updatePolling(true);
        setParsingStartTime((prev) => prev ?? Date.now());
      } else {
        updatePolling(false);
        setParsingStartTime(null);
      }
    } catch (err) {
      if (!ownsResult()) return;
      const errorMessage = err instanceof Error ? err.message : "Failed to load statement";
      consecutiveErrorsRef.current += 1;
      if (pollingRef.current && consecutiveErrorsRef.current >= 3) {
        updatePolling(false);
        setPollingStoppedReason(`Auto-refresh stopped after 3 consecutive errors. Last error: ${errorMessage}`);
        showToast("Auto-refresh stopped due to repeated errors", "error");
      }
      setError(errorMessage);
    } finally {
      if (activeRequestRef.current?.requestId === requestId) {
        activeRequestRef.current = null;
        if (mountedRef.current) setLoading(false);
      }
    }
  }, [showToast, statementId, updatePolling]);

  const resumePolling = useCallback(() => {
    setPollingStoppedReason(null);
    consecutiveErrorsRef.current = 0;
    setParsingStartTime(Date.now());
    updatePolling(true);
    void fetchStatement();
  }, [fetchStatement, updatePolling]);

  useEffect(() => {
    mountedRef.current = true;
    setLoading(true);
    setEconomicReviewRequired(false);
    setConflictsResolved(false);
    setReviewingTxn(null);
    setApprovedEntries(null);
    void fetchStatement();
    return () => {
      mountedRef.current = false;
      requestSequenceRef.current += 1;
      activeRequestRef.current?.controller.abort();
      activeRequestRef.current = null;
    };
  }, [fetchStatement]);

  useEffect(() => {
    if (!polling) return;
    const interval = setInterval(() => {
      if (parsingStartTime && Date.now() - parsingStartTime > PARSING_TIMEOUT_MS) {
        activeRequestRef.current?.controller.abort();
        activeRequestRef.current = null;
        requestSequenceRef.current += 1;
        updatePolling(false);
        setParsingStartTime(null);
        setPollingStoppedReason("Parsing has been running for over 5 minutes. It may be stuck. You can retry parsing with a different model.");
        showToast("Parsing appears stuck — stopped auto-refresh", "error");
        return;
      }
      void fetchStatement({ supersede: false });
    }, PARSING_POLL_MS);
    return () => clearInterval(interval);
  }, [polling, fetchStatement, parsingStartTime, showToast, updatePolling]);

  const reviewReady = Boolean(statement) && statement?.status !== "parsing";
  const { data: review, refetch: refetchReview } = useQuery({
    queryKey: ["statement-review", statementId],
    queryFn: () => apiOperation("get_statement_for_review_statements__statement_id__review_get", { path: { statement_id: statementId } }),
    enabled: reviewReady,
  });
  const { data: pendingStatementsData } = useQuery({
    queryKey: ["pending-statements"],
    queryFn: () => apiOperation("list_pending_review_statements_pending_review_get"),
    enabled: isParsed,
  });
  const { data: conflicts } = useQuery({
    queryKey: ["statement-conflicts", statementId],
    queryFn: () => apiOperation("get_review_conflicts_review_conflicts__statement_id__get", { path: { statement_id: statementId } }),
    enabled: isParsed,
  });

  const pendingStatements = pendingStatementsData?.items || [];
  const duplicateCandidates = conflicts?.duplicates || [];
  const transferPairCandidates = conflicts?.transfer_pairs || [];
  const sourceMissingFacts = review?.source_missing_facts || [];
  const sourceEnvelopeReviewable = Boolean(review?.source_envelope_reviewable);
  const requiresEnvelopeConfirmation = isParsed && sourceEnvelopeReviewable && !review?.reviewed_envelope;
  const requiresOtherSourceReview = isParsed && !sourceEnvelopeReviewable && sourceMissingFacts.length > 0 && !review?.reviewed_envelope;

  const { data: custodyAccountsData } = useQuery({
    queryKey: ["statement-review-custody-accounts", statementId],
    queryFn: () => apiOperation("list_accounts_accounts_get", { query: { account_type: "ASSET", is_active: true } }),
    enabled: requiresEnvelopeConfirmation,
  });

  const refreshAfterReview = () => {
    void queryClient.invalidateQueries({ queryKey: ["pending-statements"] });
    void queryClient.invalidateQueries({ queryKey: ["statement-review", statementId] });
    return fetchStatement({ supersede: true });
  };

  const approveMutation = useMutation({
    mutationFn: (variables: { autoFill?: boolean } | void) => apiOperation(
      "approve_statement_stage1_statements__statement_id__review_approve_post",
      { path: { statement_id: statementId }, body: { create_account_if_missing: !review?.account_id, auto_fill_default_categories: Boolean(variables?.autoFill) } },
    ),
    onSuccess: (result) => {
      setEconomicReviewRequired(false);
      const createdCount = result.journal_entries_created ?? 0;
      track(ANALYTICS_EVENTS.REVIEW_APPROVED, { statement_id: statementId });
      showToast(`Statement approved. ${createdCount} journal entries posted.`, "success");
      setApproveDialogOpen(false);
      setApprovedEntries(createdCount);
      void refreshAfterReview();
      if (fromAttention) router.push(ATTENTION_RETURN_HREF);
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409 && err.message.startsWith("Economic review required:")) {
        setEconomicReviewRequired(true);
        setApproveDialogOpen(false);
        showToast("Economic classification needs review before entries can be posted.", "error");
        void refetchReview();
        return;
      }
      showToast(err instanceof Error ? err.message : "Failed to approve", "error");
    },
  });

  const envelopeMutation = useMutation({
    mutationFn: () => {
      if (!review?.source_result_digest) return Promise.reject(new Error("The source result is unavailable. Re-parse the statement before confirming it."));
      return confirmStatementReviewEnvelope(statementId, {
        source_result_digest: review.source_result_digest,
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
      showToast("Source envelope confirmed. You can now continue the review.", "success");
      queryClient.invalidateQueries({ queryKey: ["statement-review", statementId] });
    },
    onError: (err) => showToast(err instanceof Error ? err.message : "Failed to confirm source facts", "error"),
  });

  const createCustodyAccountMutation = useMutation({
    mutationFn: (name: string) => apiOperation("create_account_accounts_post", { body: { name, type: "ASSET", currency: envelopeDraft.currency } }),
    onSuccess: async (account) => {
      await queryClient.invalidateQueries({ queryKey: ["statement-review-custody-accounts", statementId] });
      setEnvelopeDraft((current) => ({ ...current, accountId: account.id }));
      showToast(`Account "${account.name}" created and selected.`, "success");
    },
    onError: (err) => showToast(err instanceof Error ? err.message : "Failed to create account", "error"),
  });

  const rejectMutation = useMutation({
    mutationFn: (notes?: string) => apiOperation("reject_statement_stage1_statements__statement_id__review_reject_post", { path: { statement_id: statementId }, body: { notes: notes || null } }),
    onSuccess: () => {
      showToast("Statement rejected", "success");
      setRejectDialogOpen(false);
      void refreshAfterReview();
      if (fromAttention) router.push(ATTENTION_RETURN_HREF);
    },
    onError: (err) => showToast(err instanceof Error ? err.message : "Failed to reject", "error"),
  });

  const resolveConflictsMutation = useMutation({
    mutationFn: (action: "confirm_distinct" | "link_transfer") => apiOperation("resolve_review_conflicts_review_conflicts__statement_id__resolve_post", { path: { statement_id: statementId }, body: { action } }),
    onSuccess: () => {
      showToast("Conflicts resolved", "success");
      setConflictsResolved(true);
      setConflictDialogOpen(false);
      queryClient.invalidateQueries({ queryKey: ["statement-conflicts", statementId] });
    },
    onError: (err) => showToast(err instanceof Error ? err.message : "Failed to resolve conflicts", "error"),
  });

  useEffect(() => {
    if (!conflicts?.resolved && (duplicateCandidates.length || transferPairCandidates.length)) setConflictDialogOpen(true);
  }, [duplicateCandidates.length, transferPairCandidates.length, conflicts?.resolved]);

  useEffect(() => {
    if (!review || !requiresEnvelopeConfirmation) return;
    setEnvelopeDraft({
      accountId: review.account_id || "", currency: review.currency || "", periodStart: review.period_start || "", periodEnd: review.period_end || "",
      openingBalance: review.opening_balance?.toString() || "", closingBalance: review.closing_balance?.toString() || "", rationale: "",
    });
  }, [review, requiresEnvelopeConfirmation]);

  const handleRetry = async () => {
    setRetryLoading(true);
    setParsingStartTime(null);
    setPollingStoppedReason(null);
    try {
      await apiOperation("retry_statement_parsing_statements__statement_id__retry_post", { path: { statement_id: statementId } });
      showToast("Re-parsing started", "success");
      await fetchStatement({ supersede: true });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to retry parsing";
      showToast(msg, "error");
      setError(msg);
    } finally {
      setRetryLoading(false);
    }
  };

  const handleBrokerageImport = async () => {
    setImportLoading(true);
    setImportError(null);
    setImportResult(null);
    try {
      const result = await apiOperation("import_brokerage_statement_positions_statements__statement_id__brokerage_import_post", { path: { statement_id: statementId } });
      setImportResult(result);
      showToast("Brokerage positions imported successfully", "success");
      // The import changed the holdings and cleared a recorded failure: those reads are stale (#2648).
      void invalidatePortfolioQueries(queryClient);
      void invalidateLedgerDerivedQueries(queryClient);
    } catch (err) {
      const raw = err instanceof Error ? err.message : "Import failed";
      setImportError(raw.replace(/https?:\/\/\S+/g, "[URL]").replace(/s3:\/\/\S+/g, "[URL]"));
      showToast("Brokerage import failed", "error");
    } finally {
      setImportLoading(false);
    }
  };

  const handleDeleteStatement = async () => {
    setDeleteLoading(true);
    try {
      await apiOperation("delete_statement_statements__statement_id__delete", { path: { statement_id: statementId } });
      showToast("Statement deleted successfully", "success");
      if (typeof window !== "undefined") window.location.href = "/upload";
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Failed to delete statement", "error");
      setDeleteLoading(false);
      setDeleteDialogOpen(false);
    }
  };

  if (loading) return <div className="p-6"><LoadingState label="Loading statement" /></div>;
  if (!statement) {
    return (
      <div className="p-6">
        <div className="card p-8 text-center">
          {error ? (
            <>
              <h2 className="text-lg font-medium mb-2">Failed to load statement</h2>
              <p className="text-muted mb-4">{error}</p>
              <button type="button" onClick={() => { setLoading(true); void fetchStatement({ supersede: true }); }} className="btn-primary mr-3">Retry</button>
            </>
          ) : <p className="text-muted mb-4">Statement not found</p>}
          <Link href={returnHref} className={error ? "btn-secondary" : "btn-primary"}>{returnLabel}</Link>
        </div>
      </div>
    );
  }

  const canRetry = statement.status === "parsed" || (statement.status === "parsing" && Boolean(pollingStoppedReason));
  const canImport = !importResult && (statement.status === "parsed" || statement.status === "approved") && canImportBrokerageStatement(statement);
  const validationResult = review?.balance_validation_result ?? null;
  const balanceValid = Boolean(validationResult?.opening_match && validationResult?.closing_match);
  const hasUnresolvedConflicts = !(conflictsResolved || conflicts?.resolved) && (duplicateCandidates.length > 0 || transferPairCandidates.length > 0);
  const approvalBlockedReason = requiresEnvelopeConfirmation ? "Confirm the source facts before approving this statement."
    : requiresOtherSourceReview ? "This source has facts that a cash statement envelope cannot confirm."
    : hasUnresolvedConflicts ? "Resolve duplicate and transfer-pair candidates before approval" : null;
  const currentIndex = pendingStatements.findIndex((s) => s.id === statementId);
  const prevId = currentIndex > 0 ? pendingStatements[currentIndex - 1].id : null;
  const nextId = currentIndex >= 0 && currentIndex < pendingStatements.length - 1 ? pendingStatements[currentIndex + 1].id : null;
  const returnTo = encodeURIComponent(`/statements/${statementId}`);
  // A CSV source has no preview panel, and the table takes the full width (#2647).
  const showPreview = hasInlinePreview(statement.original_filename || statement.file_path);
  const hasDocument = Boolean(statement.file_path) && statement.status !== "parsing";

  return (
    <div className="p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <Link href={returnHref} className="text-sm text-muted hover:text-[var(--foreground)] flex items-center gap-1">← {returnLabel}</Link>
        {isParsed && pendingStatements.length > 0 && (
          <div className="flex items-center gap-2">
            <button onClick={() => prevId && router.push(statementHref(prevId))} disabled={!prevId} className="btn-ghost btn-sm disabled:opacity-30" title="Previous pending statement">← Prev</button>
            <span className="text-xs text-muted">{currentIndex + 1} / {pendingStatements.length}</span>
            <button onClick={() => nextId && router.push(statementHref(nextId))} disabled={!nextId} className="btn-ghost btn-sm disabled:opacity-30" title="Next pending statement">Next →</button>
          </div>
        )}
      </div>
      <div className="mb-6"><FlowStepBanner current="review" /></div>
      {pollingStoppedReason && (
        <div className="mb-4 p-4 border border-[var(--error)]/30 bg-[var(--error-muted)] rounded-lg">
          <div className="font-medium text-[var(--error)] mb-1">Auto-refresh Stopped</div>
          <div className="text-sm text-[var(--foreground-muted)] mb-3">{pollingStoppedReason}</div>
          <button onClick={resumePolling} className="btn-secondary text-sm">Resume Auto-Refresh</button>
        </div>
      )}
      <StatementHeader statement={statement} canImport={canImport} canRetry={canRetry} canDelete={statement.status !== "approved"} importLoading={importLoading} retryLoading={retryLoading} deleteLoading={deleteLoading} onBrokerageImport={handleBrokerageImport} onRetry={handleRetry} onDelete={() => setDeleteDialogOpen(true)} formatCode={currencyCodeOrDash} formatPeriod={formatPeriod} />
      {isParsed && review && (
        <div className="mb-4 flex justify-end">
          <ReviewActionBar onApprove={() => setApproveDialogOpen(true)} onReject={() => setRejectDialogOpen(true)} actionLoading={approveMutation.isPending || rejectMutation.isPending} balanceValid={balanceValid} statementStatus={statement.status} approvalBlockedReason={approvalBlockedReason} onResolveConflicts={hasUnresolvedConflicts ? () => setConflictDialogOpen(true) : undefined} onReparse={handleRetry} reparsePending={retryLoading} />
        </div>
      )}
      {(economicReviewRequired || statement.validation_error?.startsWith("Economic review required:")) && isParsed && (
        <section className="mb-4 rounded-lg border border-[var(--warning)]/40 bg-[var(--warning-muted)] p-4">
          <h2 className="font-semibold text-[var(--foreground)]">Transaction classifications need review</h2>
          <p className="mt-1 text-sm text-muted">These transactions need your confirmation before they can be posted into the journal. Auto-fill accepts the AI suggestion for each row and uses a general category for rows without one. A transfer or a card repayment is posted to the Processing account until the other side of the movement arrives. A loan payment goes to Loans Payable and a trade to Investments. A row in a foreign currency stays here for you. You can also review every row manually.</p>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button type="button" onClick={() => approveMutation.mutate({ autoFill: true })} disabled={approveMutation.isPending} className="btn-primary inline-flex items-center gap-2">{approveMutation.isPending ? "Approving..." : "Auto-Fill Default Categories & Approve"}</button>
            <Link href={`${NEEDS_YOU_HREF}&statement_id=${encodeURIComponent(statementId)}&return_to=${returnTo}#ai-suggestions`} className="btn-secondary inline-flex">Review AI suggestions</Link>
            <Link href={`/reconciliation?tab=unmatched&statement_id=${encodeURIComponent(statementId)}&return_to=${returnTo}`} className="btn-secondary inline-flex">Review transaction classifications</Link>
          </div>
        </section>
      )}
      {approvedNow && (
        <div className="mb-4 p-4 border border-[var(--success)]/30 bg-[var(--success-muted)] rounded-lg">
          <p className="font-medium text-[var(--success)]">Statement approved. {approvedEntries} journal entries created.</p>
          <div className="mt-2 flex items-center gap-2"><Link href="/journal" className="btn-secondary text-sm">View in Journal</Link><Link href="/reports" className="btn-secondary text-sm">Go to Reports</Link></div>
        </div>
      )}
      {importResult && <BrokerageImportResultBanner importResult={importResult} />}
      {importError && (
        <div className="mb-4 p-4 border border-[var(--error)]/30 bg-[var(--error-muted)] rounded-lg" data-testid="import-error-banner">
          <div className="font-medium text-[var(--error)] mb-1">Brokerage Import Failed</div>
          <div className="text-sm text-[var(--foreground-muted)] mb-3">{importError}</div>
          <button onClick={handleBrokerageImport} disabled={importLoading} className="btn-secondary text-sm">Retry Import</button>
        </div>
      )}
      {error && <div className="mb-4 alert-error">{error}</div>}
      {polling && (
        <div className="mb-4 card p-4"><div className="flex items-center gap-3" role="status" aria-live="polite" aria-busy="true"><div className="w-5 h-5 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" /><div className="flex-1"><div className="text-sm font-medium text-[var(--accent)]">Parsing in progress…</div><div className="text-xs text-muted mt-0.5">AI is extracting transaction data. This may take up to 3 minutes.</div></div></div></div>
      )}
      {statement.status === "rejected" && (
        <div className="mb-4 p-4 border border-[var(--error)]/30 bg-[var(--error-muted)] rounded-lg">
          <div className="font-medium text-[var(--error)] mb-1">Parsing Failed</div>
          {statement.validation_error && <div className="text-sm text-[var(--foreground-muted)] mb-3 break-words">{statement.validation_error}</div>}
          <button type="button" onClick={handleRetry} disabled={retryLoading} className="btn-secondary text-sm">{retryLoading ? "Retrying..." : "Retry Parse"}</button>
        </div>
      )}
      {review && <BalanceIndicator openingBalance={review.opening_balance} closingBalance={review.closing_balance} validationResult={validationResult} currency={review.currency || "SGD"} />}
      <SourceEnvelopeConfirmation requiresEnvelopeConfirmation={requiresEnvelopeConfirmation} requiresOtherSourceReview={requiresOtherSourceReview} sourceMissingFacts={sourceMissingFacts} missingFactLabels={MISSING_FACT_LABELS} envelopeDraft={envelopeDraft} onDraftChange={setEnvelopeDraft} custodyAccounts={custodyAccountsData?.items || []} onConfirm={() => envelopeMutation.mutate()} isPending={envelopeMutation.isPending} reviewedEnvelope={review?.reviewed_envelope} onCreateAccount={(name) => createCustodyAccountMutation.mutate(name)} isCreatingAccount={createCustodyAccountMutation.isPending} defaultAccountName={statement.institution ? `${statement.institution} account` : ""} />
      {/* Only the desktop table beside a preview has a fixed height. Without a preview, and on a phone, the
          rows grow with the page. On a phone the rows come before the preview (#2647). */}
      <div data-testid="statement-side-by-side-workbench" className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {showPreview && <div className={`order-2 lg:order-1 lg:col-span-5 ${hasDocument ? "h-[480px] lg:min-h-[540px] lg:h-[600px]" : ""}`}><PdfPreviewPane statementId={statementId} hasDocument={hasDocument} /></div>}
        <div className={`order-1 min-w-0 lg:order-2 ${showPreview ? "lg:col-span-7 lg:min-h-[540px] lg:h-[600px]" : "lg:col-span-12"}`}><TransactionTable transactions={statement.transactions} currency={statement.currency || "SGD"} onSelectTransaction={setReviewingTxn} statementStatus={statement.status} /></div>
      </div>
      <LowConfidenceReviewModal isOpen={reviewingTxn !== null} onClose={() => setReviewingTxn(null)} transaction={reviewingTxn} currency={reviewingTxn?.currency || statement.currency || "SGD"} onSuccess={() => { void refreshAfterReview(); }} />
      <ConflictResolutionDialog isOpen={conflictDialogOpen} onClose={() => setConflictDialogOpen(false)} duplicateCandidates={duplicateCandidates} transferPairCandidates={transferPairCandidates} onResolve={(action) => resolveConflictsMutation.mutate(action)} isResolving={resolveConflictsMutation.isPending} />
      <ConfirmDialog isOpen={approveDialogOpen} onCancel={() => !approveMutation.isPending && setApproveDialogOpen(false)} onConfirm={() => approveMutation.mutate()} title="Approve Statement" message={review?.account_id ? "This will approve the statement with balance validation. Proceed?" : "This will create and map an asset account for this statement, then approve it with balance validation. Proceed?"} confirmLabel="Approve" loading={approveMutation.isPending} />
      <ConfirmDialog isOpen={rejectDialogOpen} onCancel={() => !rejectMutation.isPending && setRejectDialogOpen(false)} onConfirm={(reason) => rejectMutation.mutate(reason)} title="Reject Statement" message="Parsed transactions can't be edited. To fix a mis-parse, reject this statement and re-parse it (Retry Parse) on this page. This will mark the statement as rejected." confirmLabel="Reject" confirmVariant="danger" input={{ label: "Rejection Reason (optional)", placeholder: "Enter reason for rejection..." }} loading={rejectMutation.isPending} />
      <ConfirmDialog isOpen={deleteDialogOpen} title="Delete Statement" message="Are you sure you want to delete this statement? This action cannot be undone and will remove all associated parsed transactions and errors." confirmLabel="Delete" confirmVariant="danger" loading={deleteLoading} onConfirm={handleDeleteStatement} onCancel={() => setDeleteDialogOpen(false)} />
    </div>
  );
}

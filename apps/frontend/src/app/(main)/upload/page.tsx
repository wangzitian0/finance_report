"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Trash2 } from "lucide-react";

import StatementUploader from "@/components/statements/StatementUploader";
import GuidedEvidenceForm from "@/components/assets/GuidedEvidenceForm";
import { ProcessingTransfers } from "@/components/statements/ProcessingTransfers";
import { FlowStepBanner, WorkflowNotices } from "@/components/workflow/WorkflowNotifications";
import { InfoHint } from "@/components/ui/InfoHint";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { useToast } from "@/components/ui/Toast";
import { Alert, Badge, Button, EmptyState, IconButton, LoadingState, PageHeader, type BadgeVariant } from "@/components/ui";
import { apiOperation } from "@/lib/api-client";
import { invalidateLedgerDerivedQueries, invalidatePortfolioQueries } from "@/lib/queryClient";
import { SHARED_STALE_MS, STATEMENTS_LIST_QUERY_KEY } from "@/lib/sharedQueries";
import { BankStatement, normalizeBankStatement } from "@/lib/types";
import { formatCurrencyLocale } from "@/lib/audit/money";
import { PARSING_POLL_MS, currencyCodeOrDash, statementDisplayTitle } from "@/lib/statusLabels";
import { formatPeriod } from "@/lib/date";

function statusDisplay(status: string): { label: string; variant: BadgeVariant } {
  switch (status) {
    case "approved": return { label: "Approved", variant: "success" };
    case "rejected": return { label: "Rejected", variant: "error" };
    case "parsed": return { label: "Ready to review", variant: "info" };
    case "parsing": return { label: "Parsing", variant: "muted" };
    case "uploaded": return { label: "Uploaded", variant: "muted" };
    default: return { label: status, variant: "muted" };
  }
}

/**
 * The state label of an upload row (#2648). A failed brokerage import wins over the parse state:
 * the file is parsed, but its positions are not in the portfolio. The backend sets
 * `brokerage_import_failed` only for a parsed or approved statement.
 */
function rowStateDisplay(statement: BankStatement): { label: string; variant: BadgeVariant } {
  if (statement.brokerage_import_failed) return { label: "Import failed", variant: "error" };
  return statusDisplay(statement.status);
}

/** The balance check badge (#2648). */
function balanceCheckDisplay(statement: BankStatement): { label: string; variant: BadgeVariant } {
  if (statement.balance_validated === null || statement.balance_validated === undefined) return { label: "Not checked", variant: "muted" };
  return statement.balance_validated ? { label: "✓ Verified", variant: "success" } : { label: "Needs Review", variant: "warning" };
}

export default function UploadPage() {
  const { showToast } = useToast();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deletingStatementId, setDeletingStatementId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [retryingImportId, setRetryingImportId] = useState<string | null>(null);
  const mountedRef = useRef(false);

  const statementsQuery = useQuery({
    queryKey: STATEMENTS_LIST_QUERY_KEY,
    queryFn: ({ signal }) => apiOperation("list_statements_statements_get", { signal }),
    staleTime: SHARED_STALE_MS,
    refetchOnMount: "always",
    refetchInterval: (query) => (query.state.data?.items?.some((s) => s.status === "parsing") ? PARSING_POLL_MS : false),
  });
  const listItems = statementsQuery.data?.items;
  const statements = useMemo(() => (listItems ?? []).map(normalizeBankStatement), [listItems]);
  const polling = statements.some((s) => s.status === "parsing");
  const loading = statementsQuery.isPending;
  const error = actionError ?? (statementsQuery.isError ? (statementsQuery.error?.message ?? "Failed to load statements") : null);

  const refreshStatements = useCallback(() => {
    if (!mountedRef.current) return;
    setActionError(null);
    void invalidateLedgerDerivedQueries(queryClient);
  }, [queryClient]);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const retryBrokerageImport = async (statementId: string) => {
    setRetryingImportId(statementId);
    try {
      await apiOperation("import_brokerage_statement_positions_statements__statement_id__brokerage_import_post", { path: { statement_id: statementId } });
      showToast("Brokerage positions imported", "success");
      // The import changed the holdings: the portfolio reads are stale (#2648).
      void invalidatePortfolioQueries(queryClient);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Brokerage import failed", "error");
    } finally {
      setRetryingImportId(null);
      // The server records the outcome on the statement: read the list again.
      await invalidateLedgerDerivedQueries(queryClient);
    }
  };

  const handleDeleteConfirm = async () => {
    if (!deletingStatementId || deleting) return;
    setDeleting(true);
    try {
      await apiOperation("delete_statement_statements__statement_id__delete", { path: { statement_id: deletingStatementId } });
      showToast("Statement deleted successfully", "success");
      setDeleteDialogOpen(false);
      setDeletingStatementId(null);
      await invalidateLedgerDerivedQueries(queryClient);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to delete statement");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="p-6">
      <PageHeader
        title="Upload"
        description="Drop a statement and we identify the type for you. Track parsing, review what needs you, and approve here. CSV imports and manual records are tucked away until you need them."
        className="sm:block"
      />

      <div className="mb-6"><FlowStepBanner current="upload" /></div>

      <div className="mb-3">
        <StatementUploader kind="statement" onUploadComplete={refreshStatements} onError={setActionError} />
      </div>

      {/* #2648: one workflow line under the upload control; the details fold under it. */}
      <WorkflowNotices />

      {error && <Alert variant="error" className="mb-4">{error}</Alert>}

      {polling && (
        <div className="mb-4 p-4 border border-[var(--accent)]/30 bg-[var(--accent-muted)] rounded-lg" role="status" aria-live="polite">
          <div className="flex items-center gap-3">
            <div className="w-5 h-5 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
            <div className="flex-1">
              <div className="text-sm font-medium text-[var(--accent)]">AI Parsing in Progress</div>
              <div className="text-xs text-muted">Extracting transactions from your statement — this usually takes ~2–3 minutes.</div>
            </div>
          </div>
        </div>
      )}

      <div id="statements" className="card mb-6">
        <div className="card-header flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-medium">Uploaded Statements</h3>
            {statements.length > 0 && (
              <span data-testid="upload-processing-summary">
                <Badge variant="muted">
                  {`${statements.filter((s) => s.status === "parsing").length} parsing · ${statements.filter((s) => s.status === "parsed").length} parsed · ${statements.filter((s) => s.status === "approved").length} approved`}
                </Badge>
              </span>
            )}
          </div>
          <div className="flex items-center gap-3">
            {statements.some((s) => s.status === "approved" || s.status === "parsed") && (
              <Link href="/reports?tab=balance-sheet" className="text-xs font-medium text-[var(--accent)] hover:underline">Open Reports →</Link>
            )}
            <span className="text-xs text-muted">{statements.length} total</span>
          </div>
        </div>

        {loading ? (
          <LoadingState label="Loading statements" framed={false} />
        ) : error ? (
          <EmptyState
            framed={false}
            role="alert"
            aria-live="polite"
            title="Failed to load statements"
            description={error}
            action={<Button variant="secondary" onClick={refreshStatements} aria-label="Retry loading statements">Retry</Button>}
          />
        ) : statements.length === 0 ? (
          <EmptyState framed={false} title="No statements uploaded yet" />
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {statements.map((statement) => {
              const state = rowStateDisplay(statement);
              const balanceCheck = balanceCheckDisplay(statement);
              const importFailed = state.label === "Import failed";
              const isParsing = statement.status === "parsing";
              const currency = statement.currency || "SGD";
              return (
              <div key={statement.id} data-testid={`upload-statement-row-${statement.id}`} className="relative block px-4 py-4 hover:bg-[var(--background-muted)]/50 transition-colors sm:px-6">
                {/* On a phone the actions go under the title, so the row never widens the page (#2648). */}
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
                  <div className="w-full min-w-0 flex-1">
                    <div className="flex min-w-0 items-start justify-between gap-2 mb-1 sm:justify-start">
                      <Link href={`/statements/${statement.id}`} className="min-w-0 flex-1 font-medium truncate hover:text-[var(--accent)] after:absolute after:inset-0 sm:flex-initial">
                        {statementDisplayTitle(statement)}
                      </Link>
                      <Badge variant={state.variant} className="shrink-0">
                        {isParsing && (
                          <span className="inline-block w-3 h-3 mr-1 border-2 border-current border-t-transparent rounded-full animate-spin" />
                        )}
                        {state.label}
                      </Badge>
                    </div>
                    {/* A failed import states its own reason. An earlier note in validation_error is not about the import. */}
                    {importFailed && statement.brokerage_import_failure_reason ? (
                      <div className="text-xs text-[var(--error)] mt-1 line-clamp-2 [overflow-wrap:anywhere]">{statement.brokerage_import_failure_reason}</div>
                    ) : statement.status === "rejected" && statement.validation_error ? (
                      <div className="text-xs text-[var(--error)] mt-1 line-clamp-2 [overflow-wrap:anywhere]">{statement.validation_error}</div>
                    ) : null}
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                      <span className="[overflow-wrap:anywhere]">{statement.institution}</span>
                      <span>•</span>
                      <span className="whitespace-nowrap">{formatPeriod(statement.period_start, statement.period_end, isParsing ? "Parsing..." : undefined)}</span>
                      <span>•</span>
                      <span>{currencyCodeOrDash(statement.currency)}</span>
                    </div>
                  </div>
                  <div className="relative z-10 flex flex-wrap items-center gap-2 sm:flex-shrink-0 sm:flex-col sm:items-end">
                    {importFailed ? (
                      <Button variant="primary" className="text-sm" disabled={retryingImportId === statement.id} onClick={() => void retryBrokerageImport(statement.id)}>
                        {retryingImportId === statement.id ? "Retrying..." : "Retry import"}
                      </Button>
                    ) : statement.status === "parsed" ? (
                      <div className="flex flex-wrap items-center gap-2">
                        <Button variant="primary" className="text-sm" onClick={() => router.push(`/statements/${statement.id}`)}>Review & Approve →</Button>
                        <Button variant="secondary" className="text-xs hidden sm:inline-flex" onClick={() => router.push("/reports?tab=balance-sheet")}>View Report</Button>
                      </div>
                    ) : statement.status === "approved" ? (
                      <div className="flex flex-wrap items-center gap-2">
                        <Button variant="secondary" className="text-sm" onClick={() => router.push(`/statements/${statement.id}`)}>View Transactions</Button>
                        <Button variant="secondary" className="text-sm" onClick={() => router.push("/reports?tab=balance-sheet")}>View Report →</Button>
                      </div>
                    ) : null}
                    <IconButton
                      icon={Trash2}
                      label="Delete Statement"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        setDeletingStatementId(statement.id);
                        setDeleteDialogOpen(true);
                      }}
                      className="text-muted hover:text-[var(--error)]"
                    />
                    {!isParsing && (
                      <div className="sm:text-right">
                        <div className="text-lg font-semibold text-[var(--accent)]">{statement.confidence_score ?? "—"}%</div>
                        <div className="text-xs text-muted">confidence</div>
                      </div>
                    )}
                  </div>
                </div>

                {!isParsing && (
                  <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2 text-xs">
                    <div>
                      <span className="text-muted">Opening:</span>{" "}
                      <span>{statement.opening_balance == null ? "—" : formatCurrencyLocale(statement.opening_balance, currency)}</span>
                    </div>
                    <div>
                      <span className="text-muted">Closing:</span>{" "}
                      <span>{statement.closing_balance == null ? "—" : formatCurrencyLocale(statement.closing_balance, currency)}</span>
                    </div>
                    {balanceCheck.label === "Needs Review" ? (
                      <span className="relative z-10 inline-flex items-center">
                        <Badge variant="warning">Needs Review</Badge>
                        <InfoHint term="needs_review" label="Needs review" />
                      </span>
                    ) : (
                      <Badge variant={balanceCheck.variant}>{balanceCheck.label}</Badge>
                    )}
                  </div>
                )}
              </div>
              );
            })}
          </div>
        )}
      </div>

      <ProcessingTransfers />

      <details className="card mb-3 group">
        <summary className="card-header flex items-center justify-between cursor-pointer list-none">
          <span className="text-sm font-medium">CSV import</span>
          <span className="text-xs text-muted">Non-standard columns are mapped automatically</span>
        </summary>
        <div className="card-body">
          <StatementUploader kind="csv" onUploadComplete={refreshStatements} onError={setActionError} />
        </div>
      </details>

      <details className="card mb-6 group">
        <summary className="card-header flex items-center justify-between cursor-pointer list-none">
          <span className="text-sm font-medium">Manual records</span>
          <span className="text-xs text-muted">ESOP / RSU, property, and other manual-trusted evidence</span>
        </summary>
        <div className="card-body"><GuidedEvidenceForm /></div>
      </details>

      <ConfirmDialog
        isOpen={deleteDialogOpen}
        onCancel={() => { setDeleteDialogOpen(false); setDeletingStatementId(null); }}
        onConfirm={handleDeleteConfirm}
        loading={deleting}
        title="Delete Statement"
        message="Are you sure you want to delete this statement? This action cannot be undone."
        confirmLabel="Delete Statement"
        confirmVariant="danger"
      />
    </div>
  );
}

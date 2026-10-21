"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Trash2 } from "lucide-react";

import StatementUploader from "@/components/statements/StatementUploader";
import GuidedEvidenceForm from "@/components/assets/GuidedEvidenceForm";
import { FlowStepBanner } from "@/components/workflow/FlowStepBanner";
import { InfoHint } from "@/components/ui/InfoHint";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { useToast } from "@/components/ui/Toast";
import {
  Alert,
  Badge,
  Button,
  EmptyState,
  IconButton,
  LoadingState,
  PageHeader,
} from "@/components/ui";
import type { BadgeVariant } from "@/components/ui";
import { apiOperation } from "@/lib/api-client";
import { invalidateLedgerDerivedQueries } from "@/lib/queryClient";
import { statementsListQuery } from "@/lib/sharedQueries";
import { BankStatement, normalizeBankStatement } from "@/lib/types";
import { formatCurrencyLocale } from "@/lib/audit/money";
import { currencyCodeOrDash } from "@/lib/statusLabels";
import { formatPeriod } from "@/lib/date";

// Plain-language status for everyday users. "parsed" means the AI finished and
// it is the user's turn to review — surface that as an action, not a warning.
function statusDisplay(status: string): {
  label: string;
  variant: BadgeVariant;
} {
  switch (status) {
    case "approved":
      return { label: "Approved", variant: "success" };
    case "rejected":
      return { label: "Rejected", variant: "error" };
    case "parsed":
      return { label: "Ready to review", variant: "info" };
    case "parsing":
      return { label: "Parsing", variant: "muted" };
    case "uploaded":
      return { label: "Uploaded", variant: "muted" };
    default:
      return { label: status, variant: "muted" };
  }
}

function statementDisplayTitle(statement: BankStatement): string {
  return (
    statement.original_filename ||
    `${statement.institution} (${statement.period_start ?? ""} – ${statement.period_end ?? ""})`
  );
}

/** Poll interval while a statement parses. The poll stops when no statement parses. */
const PARSING_POLL_MS = 3000;

export default function UploadPage() {
  const { showToast } = useToast();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deletingStatementId, setDeletingStatementId] = useState<string | null>(
    null,
  );
  const [deleting, setDeleting] = useState(false);
  const mountedRef = useRef(false);

  // The lean statement list (no transactions) through the shared query cache (#2583 S4).
  // React Query keeps one request in flight, aborts it on unmount, and polls only while a
  // statement parses: the interval function returns false once nothing parses.
  const statementsQuery = useQuery({
    ...statementsListQuery(),
    // Show the current list on arrival: the user may come from an upload or a review.
    refetchOnMount: "always",
    refetchInterval: (query) =>
      query.state.data?.items.some((s) => s.status === "parsing")
        ? PARSING_POLL_MS
        : false,
  });
  const listItems = statementsQuery.data?.items;
  const statements = useMemo(
    () => (listItems ?? []).map(normalizeBankStatement),
    [listItems],
  );
  const polling = statements.some((s) => s.status === "parsing");
  const loading = statementsQuery.isPending;
  const error =
    actionError ??
    (statementsQuery.isError
      ? (statementsQuery.error?.message ?? "Failed to load statements")
      : null);

  const refreshStatements = useCallback(() => {
    if (!mountedRef.current) return;
    setActionError(null);
    // A new upload changes the list, the workflow status and every ledger-derived read model.
    void invalidateLedgerDerivedQueries(queryClient);
  }, [queryClient]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const handleDeleteStatement = (e: React.MouseEvent, id: string) => {
    e.preventDefault();
    e.stopPropagation();
    setDeletingStatementId(id);
    setDeleteDialogOpen(true);
  };

  const handleDeleteConfirm = async () => {
    if (!deletingStatementId || deleting) return;
    setDeleting(true);
    try {
      await apiOperation("delete_statement_statements__statement_id__delete", {
        path: { statement_id: deletingStatementId },
      });
      showToast("Statement deleted successfully", "success");
      setDeleteDialogOpen(false);
      setDeletingStatementId(null);
      await invalidateLedgerDerivedQueries(queryClient);
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "Failed to delete statement",
      );
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="p-6">
      <PageHeader
        title="Upload"
        description="Drop a statement and we identify the type for you. CSV imports and manual records are tucked away until you need them."
        className="sm:block"
      />

      <div className="mb-6">
        <FlowStepBanner current="upload" />
      </div>

      {/* #1208-followup: ONE statement entry (the AI identifies bank /
                brokerage / settlement / etc. — the user never pre-classifies),
                with CSV and Manual as folded secondary entries. This replaces the
                per-source-class intake checklist, which drifted from the
                single-entry + LLM-typed + passive design. */}
      <div className="mb-6">
        <StatementUploader
          kind="statement"
          onUploadComplete={refreshStatements}
          onError={setActionError}
        />
      </div>

      {/* Error Display */}
      {error && (
        <Alert variant="error" className="mb-4">
          {error}
        </Alert>
      )}

      {/* Parsing status — AC22.11.1: an honest indeterminate state. We do
                not know real percent-complete, so we show activity + a time
                expectation instead of a fabricated fixed-width progress bar. */}
      {polling && (
        <div
          className="mb-4 p-4 border border-[var(--accent)]/30 bg-[var(--accent-muted)] rounded-lg"
          role="status"
          aria-live="polite"
        >
          <div className="flex items-center gap-3">
            <div className="w-5 h-5 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
            <div className="flex-1">
              <div className="text-sm font-medium text-[var(--accent)]">
                AI Parsing in Progress
              </div>
              <div className="text-xs text-muted">
                Extracting transactions from your statement — this usually takes
                ~2–3 minutes.
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Statements List */}
      <div className="card mb-6">
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
            {statements.some((s) => s.status === "parsing") && (
              <Link
                href="/processing"
                className="text-xs font-medium text-[var(--accent)] hover:underline"
              >
                Processing Queue →
              </Link>
            )}
            {statements.some((s) => s.status === "approved" || s.status === "parsed") && (
              <Link
                href="/reports/balance-sheet"
                className="text-xs font-medium text-[var(--accent)] hover:underline"
              >
                Open Reports →
              </Link>
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
            action={
              <Button
                variant="secondary"
                onClick={refreshStatements}
                aria-label="Retry loading statements"
              >
                Retry
              </Button>
            }
          />
        ) : statements.length === 0 ? (
          <EmptyState framed={false} title="No statements uploaded yet" />
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {statements.map((statement) => (
              <div
                key={statement.id}
                className="relative block px-6 py-4 hover:bg-[var(--background-muted)]/50 transition-colors"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      {/* Stretched link: makes the whole row open the detail page while
                                                keeping the action buttons as non-nested, separately clickable
                                                elements (valid HTML, no <button> inside <a>). */}
                      <Link
                        href={`/statements/${statement.id}`}
                        className="font-medium truncate hover:text-[var(--accent)] after:absolute after:inset-0"
                      >
                        {statementDisplayTitle(statement)}
                      </Link>
                      <Badge variant={statusDisplay(statement.status).variant}>
                        {statement.status === "parsing" && (
                          <span className="inline-block w-3 h-3 mr-1 border-2 border-current border-t-transparent rounded-full animate-spin" />
                        )}
                        {statusDisplay(statement.status).label}
                      </Badge>
                    </div>
                    {statement.status === "rejected" &&
                      statement.validation_error && (
                        <div className="text-xs text-[var(--error)] mt-1 line-clamp-2">
                          {statement.validation_error}
                        </div>
                      )}
                    <div className="flex flex-wrap items-center gap-3 text-xs text-muted">
                      <span>{statement.institution}</span>
                      <span>•</span>
                      <span>
                        {formatPeriod(
                          statement.period_start,
                          statement.period_end,
                        )}
                      </span>
                      <span>•</span>
                      <span>{currencyCodeOrDash(statement.currency)}</span>
                      <span>•</span>
                      <Link
                        href={`/statements/${statement.id}/review`}
                        className="relative z-10 font-medium text-[var(--accent)] hover:underline"
                      >
                        Compare with PDF
                      </Link>
                    </div>
                  </div>
                  <div className="relative z-10 text-right flex-shrink-0 flex flex-col items-end gap-2">
                    {statement.status === "parsed" && (
                      <div className="flex items-center gap-2">
                        <Button
                          variant="primary"
                          className="text-sm"
                          onClick={() =>
                            router.push(`/statements/${statement.id}/review`)
                          }
                        >
                          Review & Approve →
                        </Button>
                        <Button
                          variant="secondary"
                          className="text-xs hidden sm:inline-flex"
                          onClick={() =>
                            router.push("/reports/balance-sheet")
                          }
                        >
                          View Report
                        </Button>
                      </div>
                    )}
                    {statement.status === "approved" && (
                      <div className="flex items-center gap-2">
                        <Button
                          variant="secondary"
                          className="text-sm"
                          onClick={() =>
                            router.push(`/statements/${statement.id}`)
                          }
                        >
                          View Transactions
                        </Button>
                        <Button
                          variant="secondary"
                          className="text-sm"
                          onClick={() =>
                            router.push("/reports/balance-sheet")
                          }
                        >
                          View Report →
                        </Button>
                      </div>
                    )}
                    <IconButton
                      icon={Trash2}
                      label="Delete Statement"
                      onClick={(e) => handleDeleteStatement(e, statement.id)}
                      className="text-muted hover:text-[var(--error)]"
                    />
                    <div>
                      <div className="text-lg font-semibold text-[var(--accent)]">
                        {statement.confidence_score ?? "—"}%
                      </div>
                      <div className="text-xs text-muted">confidence</div>
                    </div>
                  </div>
                </div>

                <div className="mt-3 flex items-center gap-6 text-xs">
                  <div>
                    <span className="text-muted">Opening:</span>{" "}
                    <span>
                      {formatCurrencyLocale(
                        statement.opening_balance ?? 0,
                        statement.currency || "SGD",
                      )}
                    </span>
                  </div>
                  <div>
                    <span className="text-muted">Closing:</span>{" "}
                    <span>
                      {formatCurrencyLocale(
                        statement.closing_balance ?? 0,
                        statement.currency || "SGD",
                      )}
                    </span>
                  </div>
                  {statement.balance_validated === null ||
                  statement.balance_validated === undefined ? (
                    <Badge variant="muted">Parsing</Badge>
                  ) : statement.balance_validated ? (
                    <Badge variant="success">✓ Verified</Badge>
                  ) : (
                    <span className="relative z-10 inline-flex items-center">
                      <Badge variant="warning">Needs Review</Badge>
                      <InfoHint term="needs_review" label="Needs review" />
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* CSV import — separate because non-standard column headers need
                their own server-side mapping. Folded by default. */}
      <details className="card mb-3 group">
        <summary className="card-header flex items-center justify-between cursor-pointer list-none">
          <span className="text-sm font-medium">CSV import</span>
          <span className="text-xs text-muted">
            Non-standard columns are mapped automatically
          </span>
        </summary>
        <div className="card-body">
          <StatementUploader
            kind="csv"
            onUploadComplete={refreshStatements}
            onError={setActionError}
          />
        </div>
      </details>

      {/* Manual records — assets no statement can verify (ESOP/RSU,
                property, …). Trusted because the user supplied them; clearly
                labelled as manual. Folded by default. */}
      <details className="card mb-6 group">
        <summary className="card-header flex items-center justify-between cursor-pointer list-none">
          <span className="text-sm font-medium">Manual records</span>
          <span className="text-xs text-muted">
            ESOP / RSU, property, and other manual-trusted evidence
          </span>
        </summary>
        <div className="card-body">
          <GuidedEvidenceForm />
        </div>
      </details>

      <ConfirmDialog
        isOpen={deleteDialogOpen}
        onCancel={() => {
          setDeleteDialogOpen(false);
          setDeletingStatementId(null);
        }}
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

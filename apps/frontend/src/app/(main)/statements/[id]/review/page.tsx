"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";

import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { useToast } from "@/components/ui/Toast";
import { apiFetch } from "@/lib/api";
import type { MoneyValue } from "@/lib/types";

import { FlowStepBanner } from "@/components/workflow/FlowStepBanner";
import { BalanceIndicator } from "@/components/review/BalanceIndicator";
import { PdfPreviewPane } from "@/components/review/PdfPreviewPane";
import { ReviewActionBar } from "@/components/review/ReviewActionBar";
import { TransactionTable, Transaction } from "@/components/review/TransactionTable";
import { ConflictResolutionDialog } from "@/components/review/ConflictResolutionDialog";
import {
    ATTENTION_RETURN_HREF,
    ATTENTION_RETURN_LABEL,
    isAttentionOrigin,
    withAttentionSource,
} from "@/lib/attentionNavigation";

interface BalanceValidationResult {
    opening_balance: string;
    closing_balance: string;
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
}

interface ConflictCandidate {
    description: string;
    txn_date: string;
    amount: MoneyValue;
}

interface ReviewConflicts {
    duplicates: ConflictCandidate[];
    transfer_pairs: ConflictCandidate[];
}

interface Stage1ApprovalResponse {
    journal_entries_created: number;
}

export default function StatementReviewPage() {
    const { showToast } = useToast();
    const params = useParams();
    const router = useRouter();
    const searchParams = useSearchParams();
    const statementId = params.id as string;
    const fromAttention = isAttentionOrigin(searchParams);
    const returnHref = fromAttention ? ATTENTION_RETURN_HREF : "/statements";
    const returnLabel = fromAttention ? ATTENTION_RETURN_LABEL : "Back to Statements";
    const statementReviewHref = (id: string) =>
        fromAttention ? withAttentionSource(`/statements/${id}/review`) : `/statements/${id}/review`;

    const [approveDialogOpen, setApproveDialogOpen] = useState(false);
    const [rejectDialogOpen, setRejectDialogOpen] = useState(false);
    const [conflictDialogOpen, setConflictDialogOpen] = useState(false);
    const [conflictsResolved, setConflictsResolved] = useState(false);

    // Queries
    const { data, isLoading: loading, error, refetch } = useQuery({
        queryKey: ["statement-review", statementId],
        queryFn: () => apiFetch<StatementReview>(`/api/statements/${statementId}/review`),
    });

    const { data: pendingStatementsData } = useQuery({
        queryKey: ["pending-statements"],
        queryFn: () => apiFetch<{ items: Array<{ id: string }> }>("/api/statements/pending-review"),
    });

    const { data: conflicts } = useQuery({
        queryKey: ["statement-conflicts", statementId],
        queryFn: () => apiFetch<ReviewConflicts>(`/api/review/conflicts/${statementId}`),
    });

    const pendingStatements = pendingStatementsData?.items || [];
    const duplicateCandidates = conflicts?.duplicates || [];
    const transferPairCandidates = conflicts?.transfer_pairs || [];

    // Mutations
    const approveMutation = useMutation({
        mutationFn: () => apiFetch<Stage1ApprovalResponse>(`/api/statements/${statementId}/review/approve`, {
            method: "POST",
            body: JSON.stringify({ create_account_if_missing: !data?.account_id }),
        }),
        onSuccess: (result) => {
            const createdCount = result.journal_entries_created ?? 0;
            showToast(`Statement approved. ${createdCount} journal entries posted.`, "success");
            setApproveDialogOpen(false);
            router.push(
                fromAttention
                    ? ATTENTION_RETURN_HREF
                    : `/statements/${statementId}?approved=1&entriesCreated=${createdCount}`,
            );
        },
        onError: (err) => showToast(err instanceof Error ? err.message : "Failed to approve", "error")
    });

    const rejectMutation = useMutation({
        mutationFn: (notes?: string) => apiFetch(`/api/statements/${statementId}/review/reject`, {
            method: "POST",
            body: JSON.stringify({ notes: notes || null }),
        }),
        onSuccess: () => {
            showToast("Statement rejected", "success");
            setRejectDialogOpen(false);
            router.push(fromAttention ? ATTENTION_RETURN_HREF : "/statements");
        },
        onError: (err) => showToast(err instanceof Error ? err.message : "Failed to reject", "error")
    });

    // #962 / AC16.34.1: resolve the duplicate/transfer-pair candidates so a
    // legitimately-conflicting statement can be approved instead of being stuck.
    const resolveConflictsMutation = useMutation({
        mutationFn: (action: "confirm_distinct" | "link_transfer") =>
            apiFetch(`/api/review/conflicts/${statementId}/resolve`, {
                method: "POST",
                body: JSON.stringify({ action }),
            }),
        onSuccess: () => {
            showToast("Conflicts resolved", "success");
            setConflictsResolved(true);
            setConflictDialogOpen(false);
        },
        onError: (err) => showToast(err instanceof Error ? err.message : "Failed to resolve conflicts", "error"),
    });

    // EPIC-022 AC22.5.2: re-parse in place when a balance mismatch blocks approval,
    // instead of forcing a reject -> back-to-detail -> retry detour.
    const reparseMutation = useMutation({
        mutationFn: () => apiFetch(`/api/statements/${statementId}/retry`, { method: "POST" }),
        onSuccess: () => {
            showToast("Re-parsing started", "success");
            router.push(fromAttention ? ATTENTION_RETURN_HREF : `/statements/${statementId}`);
        },
        onError: (err) => showToast(err instanceof Error ? err.message : "Failed to re-parse", "error")
    });

    useEffect(() => {
        if (duplicateCandidates.length || transferPairCandidates.length) {
            setConflictDialogOpen(true);
        }
    }, [duplicateCandidates.length, transferPairCandidates.length]);

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
                            <h2 className="text-lg font-medium mb-2">Failed to load statement</h2>
                            <p className="text-muted mb-6">{error instanceof Error ? error.message : "Unknown error"}</p>
                            <div className="flex gap-3 justify-center">
                                <button type="button" onClick={() => refetch()} className="btn-primary">
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
        data.balance_validation_result?.opening_match && data.balance_validation_result?.closing_match
    );
    const hasUnresolvedConflicts =
        !conflictsResolved && (duplicateCandidates.length > 0 || transferPairCandidates.length > 0);
    const approvalBlockedReason = hasUnresolvedConflicts
        ? "Resolve duplicate and transfer-pair candidates before approval"
        : null;

    return (
        <div className="flex min-h-[calc(100vh-2rem)] w-full max-w-full min-w-0 flex-col overflow-x-hidden p-4 md:p-6 2xl:h-[calc(100vh-2rem)]">
            <div className="mb-4 flex min-w-0 max-w-full flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <Link href={returnHref} className="flex min-w-0 items-center gap-1 text-sm text-muted hover:text-[var(--foreground)]">
                    <ChevronLeft className="h-4 w-4" aria-hidden="true" />
                    <span className="truncate">{returnLabel}</span>
                </Link>

                <div className="flex min-w-0 max-w-full items-center gap-2 overflow-x-auto">
                    {(() => {
                        const currentIndex = pendingStatements.findIndex((s) => s.id === statementId);
                        const prevId = currentIndex > 0 ? pendingStatements[currentIndex - 1].id : null;
                        const nextId = currentIndex >= 0 && currentIndex < pendingStatements.length - 1 ? pendingStatements[currentIndex + 1].id : null;

                        return (
                            <>
                                <button
                                    onClick={() => prevId && router.push(statementReviewHref(prevId))}
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
                                    onClick={() => nextId && router.push(statementReviewHref(nextId))}
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
                        {data.institution} • {data.currency || "—"} • {data.period_start || "?"} to {data.period_end || "?"}
                    </p>
                </div>
                <ReviewActionBar
                    onApprove={() => setApproveDialogOpen(true)}
                    onReject={() => setRejectDialogOpen(true)}
                    actionLoading={approveMutation.isPending || rejectMutation.isPending}
                    balanceValid={balanceValid}
                    approvalBlockedReason={approvalBlockedReason}
                    onResolveConflicts={() => setConflictDialogOpen(true)}
                    onReparse={() => reparseMutation.mutate()}
                    reparsePending={reparseMutation.isPending}
                />
            </div>

            <BalanceIndicator
                openingBalance={data.opening_balance}
                closingBalance={data.closing_balance}
                validationResult={data.balance_validation_result}
                currency={data.currency || "SGD"}
            />

            <div className="grid min-w-0 flex-1 grid-cols-1 gap-4 2xl:min-h-0 2xl:grid-cols-2">
                <PdfPreviewPane pdfUrl={data.pdf_url} />

                <TransactionTable
                    transactions={data.transactions}
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
                onCancel={() => !approveMutation.isPending && setApproveDialogOpen(false)}
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
                showInput
                inputLabel="Rejection Reason (optional)"
                inputPlaceholder="Enter reason for rejection..."
                loading={rejectMutation.isPending}
            />
        </div>
    );
}

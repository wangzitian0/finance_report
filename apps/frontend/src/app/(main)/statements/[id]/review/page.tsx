"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { useToast } from "@/components/ui/Toast";
import { apiFetch } from "@/lib/api";

import { BalanceIndicator } from "@/components/review/BalanceIndicator";
import { PdfPreviewPane } from "@/components/review/PdfPreviewPane";
import { ReviewActionBar } from "@/components/review/ReviewActionBar";
import { TransactionTable, Transaction } from "@/components/review/TransactionTable";
import { ConflictResolutionDialog } from "@/components/review/ConflictResolutionDialog";

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
    original_filename: string;
    institution: string;
    currency: string | null;
    period_start: string | null;
    period_end: string | null;
    opening_balance: string | number | null;
    closing_balance: string | number | null;
    status: string;
    stage1_status: string | null;
    balance_validation_result: BalanceValidationResult | null;
    pdf_url: string | null;
    transactions: Transaction[];
    // TODO(epic-016-conflict-detection): Backend needs to expose these
    duplicate_candidates?: any[];
    transfer_pair_candidates?: any[];
}

interface Stage1ApprovalResponse {
    journal_entries_created: number;
}

export default function StatementReviewPage() {
    const { showToast } = useToast();
    const params = useParams();
    const router = useRouter();
    const statementId = params.id as string;
    const queryClient = useQueryClient();

    const [pendingEdits, setPendingEdits] = useState<Map<string, Partial<{ description: string; amount: string; direction: string; txn_date: string }>>>(new Map());
    const [approveDialogOpen, setApproveDialogOpen] = useState(false);
    const [rejectDialogOpen, setRejectDialogOpen] = useState(false);
    const [conflictDialogOpen, setConflictDialogOpen] = useState(false);

    // Queries
    const { data, isLoading: loading, error, refetch } = useQuery({
        queryKey: ["statement-review", statementId],
        queryFn: () => apiFetch<StatementReview>(`/api/statements/${statementId}/review`),
    });

    const { data: pendingStatementsData } = useQuery({
        queryKey: ["pending-statements"],
        queryFn: () => apiFetch<{ items: Array<{ id: string }> }>("/api/statements/pending-review"),
    });

    const pendingStatements = pendingStatementsData?.items || [];

    // Mutations
    const editMutation = useMutation({
        mutationFn: async (edits: any[]) => {
            return apiFetch(`/api/statements/${statementId}/review/edit`, {
                method: "POST",
                body: JSON.stringify({ edits }),
            });
        },
        onMutate: async (edits) => {
            await queryClient.cancelQueries({ queryKey: ["statement-review", statementId] });
            const previousData = queryClient.getQueryData<StatementReview>(["statement-review", statementId]);

            if (previousData) {
                const updatedTransactions = previousData.transactions.map(txn => {
                    const edit = edits.find((e: any) => e.txn_id === txn.id);
                    if (edit) {
                        const { txn_id: _txnId, ...transactionUpdates } = edit;
                        return { ...txn, ...transactionUpdates };
                    }
                    return txn;
                });
                queryClient.setQueryData(["statement-review", statementId], {
                    ...previousData,
                    transactions: updatedTransactions
                });
            }

            return { previousData };
        },
        onError: (err, edits, context) => {
            if (context?.previousData) {
                queryClient.setQueryData(["statement-review", statementId], context.previousData);
            }
            showToast(err instanceof Error ? err.message : "Failed to save edits", "error");
        },
        onSuccess: () => {
            showToast("Edits saved successfully", "success");
            setPendingEdits(new Map());
            refetch();
        }
    });

    const approveMutation = useMutation({
        mutationFn: () => apiFetch<Stage1ApprovalResponse>(`/api/statements/${statementId}/review/approve`, { method: "POST" }),
        onSuccess: (result) => {
            const createdCount = result.journal_entries_created ?? 0;
            showToast(`Statement approved. ${createdCount} journal entries posted.`, "success");
            setApproveDialogOpen(false);
            router.push(`/statements/${statementId}?approved=1&entriesCreated=${createdCount}`);
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
            router.push("/statements");
        },
        onError: (err) => showToast(err instanceof Error ? err.message : "Failed to reject", "error")
    });

    const handleSaveEdits = () => {
        const edits = Array.from(pendingEdits.entries()).map(([txn_id, fields]) => ({
            txn_id,
            ...fields,
        }));
        editMutation.mutate(edits);
    };

    const handleDiscardEdits = () => {
        setPendingEdits(new Map());
    };

    const handleEditChange = (txnId: string, field: string, value: string) => {
        setPendingEdits((prev) => {
            const newMap = new Map(prev);
            const currentEdit = newMap.get(txnId) || {};
            newMap.set(txnId, { ...currentEdit, [field]: value });
            return newMap;
        });
    };

    useEffect(() => {
        if (data?.duplicate_candidates?.length || data?.transfer_pair_candidates?.length) {
            setConflictDialogOpen(true);
        }
    }, [data]);

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
                                <Link href="/statements" className="btn-secondary">
                                    Back to Statements
                                </Link>
                            </div>
                        </>
                    ) : (
                        <>
                            <p className="text-muted mb-6">Statement not found</p>
                            <Link href="/statements" className="btn-primary">
                                Back to Statements
                            </Link>
                        </>
                    )}
                </div>
            </div>
        );
    }

    const balanceValid = data.balance_validation_result?.closing_match ?? false;

    return (
        <div className="p-6 h-[calc(100vh-2rem)] flex flex-col">
            <div className="mb-4 flex items-center justify-between">
                <Link href="/statements" className="text-sm text-muted hover:text-[var(--foreground)] flex items-center gap-1">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                    </svg>
                    Back to Statements
                </Link>

                <div className="flex items-center gap-2">
                    {(() => {
                        const currentIndex = pendingStatements.findIndex((s) => s.id === statementId);
                        const prevId = currentIndex > 0 ? pendingStatements[currentIndex - 1].id : null;
                        const nextId = currentIndex >= 0 && currentIndex < pendingStatements.length - 1 ? pendingStatements[currentIndex + 1].id : null;

                        return (
                            <>
                                <button
                                    onClick={() => prevId && router.push(`/statements/${prevId}/review`)}
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
                                    onClick={() => nextId && router.push(`/statements/${nextId}/review`)}
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

            <div className="page-header flex items-start justify-between gap-4 mb-4">
                <div>
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
                />
            </div>

            <BalanceIndicator 
                openingBalance={data.opening_balance}
                closingBalance={data.closing_balance}
                validationResult={data.balance_validation_result}
                currency={data.currency || "SGD"}
            />

            <div className="flex-1 grid grid-cols-1 lg:grid-cols-2 gap-4 min-h-0">
                <PdfPreviewPane pdfUrl={data.pdf_url} />

                <TransactionTable 
                    transactions={data.transactions}
                    currency={data.currency || "SGD"}
                    onEdit={handleEditChange}
                    pendingEdits={pendingEdits}
                    onSave={handleSaveEdits}
                    onDiscard={handleDiscardEdits}
                    actionLoading={editMutation.isPending}
                />
            </div>

            <ConflictResolutionDialog 
                isOpen={conflictDialogOpen}
                onClose={() => setConflictDialogOpen(false)}
                duplicateCandidates={data.duplicate_candidates || []}
                transferPairCandidates={data.transfer_pair_candidates || []}
            />

            <ConfirmDialog
                isOpen={approveDialogOpen}
                onCancel={() => !approveMutation.isPending && setApproveDialogOpen(false)}
                onConfirm={() => approveMutation.mutate()}
                title="Approve Statement"
                message="This will approve the statement with balance validation. Proceed?"
                confirmLabel="Approve"
                loading={approveMutation.isPending}
            />

            <ConfirmDialog
                isOpen={rejectDialogOpen}
                onCancel={() => !rejectMutation.isPending && setRejectDialogOpen(false)}
                onConfirm={(reason) => rejectMutation.mutate(reason)}
                title="Reject Statement"
                message="This will mark the statement as rejected. You can re-parse it later."
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

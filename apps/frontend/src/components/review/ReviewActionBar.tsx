"use client";

interface ReviewActionBarProps {
    onApprove: () => void;
    onReject: () => void;
    actionLoading: boolean;
    balanceValid: boolean;
    approvalBlockedReason?: string | null;
    // EPIC-022 AC22.5.2: in-place escapes when Approve is blocked, so the user
    // never has to leave the review page to make progress.
    onResolveConflicts?: () => void;
    onReparse?: () => void;
    reparsePending?: boolean;
}

export function ReviewActionBar({
    onApprove,
    onReject,
    actionLoading,
    balanceValid,
    approvalBlockedReason = null,
    onResolveConflicts,
    onReparse,
    reparsePending = false,
}: ReviewActionBarProps) {
    const blockedByReview = Boolean(approvalBlockedReason);
    const blockedByConflicts = blockedByReview && Boolean(onResolveConflicts);
    const blockedByBalance = !blockedByReview && !balanceValid;
    const isBlocked = blockedByReview || blockedByBalance;

    const reason = blockedByConflicts
        ? "Approve is paused — we found possible duplicate or transfer-pair transactions. Review them before approving."
        : blockedByReview
          ? approvalBlockedReason || "Approve is paused until the required review is complete."
        : blockedByBalance
          ? "Approve is paused — this statement's closing balance doesn't match its transactions. Re-parsing usually fixes this."
          : "";

    return (
        <div className="flex w-full flex-col gap-2 sm:w-auto sm:items-end">
            <div className="grid w-full grid-cols-2 gap-2 sm:flex sm:w-auto sm:items-center">
                <button
                    type="button"
                    onClick={onReject}
                    disabled={actionLoading}
                    className="btn-secondary text-[var(--error)] border-[var(--error)]/30 hover:bg-[var(--error-muted)]"
                >
                    Reject
                </button>
                <button
                    type="button"
                    onClick={onApprove}
                    disabled={actionLoading || isBlocked}
                    className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
                    title={reason}
                >
                    {actionLoading ? "Processing..." : "Approve"}
                </button>
            </div>

            {isBlocked && (
                <div
                    role="status"
                    className="flex w-full flex-col gap-2 rounded-md border border-[var(--warning)]/30 bg-[var(--warning-muted)] p-3 text-sm sm:max-w-sm"
                >
                    <p className="text-[var(--foreground)]">{reason}</p>
                    {blockedByConflicts && onResolveConflicts && (
                        <button type="button" onClick={onResolveConflicts} className="btn-secondary btn-sm self-start">
                            Resolve conflicts
                        </button>
                    )}
                    {blockedByBalance && onReparse && (
                        <button
                            type="button"
                            onClick={onReparse}
                            disabled={reparsePending}
                            className="btn-secondary btn-sm self-start disabled:opacity-50"
                        >
                            {reparsePending ? "Re-parsing…" : "Re-parse statement"}
                        </button>
                    )}
                </div>
            )}
        </div>
    );
}

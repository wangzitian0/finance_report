"use client";

interface ReviewActionBarProps {
    onApprove: () => void;
    onReject: () => void;
    actionLoading: boolean;
    balanceValid: boolean;
    approvalBlockedReason?: string | null;
}

export function ReviewActionBar({
    onApprove,
    onReject,
    actionLoading,
    balanceValid,
    approvalBlockedReason = null
}: ReviewActionBarProps) {
    const disabledReason =
        approvalBlockedReason || (!balanceValid ? "Balance validation failed - cannot approve" : "");

    return (
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
                disabled={actionLoading || Boolean(disabledReason)}
                className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
                title={disabledReason}
            >
                {actionLoading ? "Processing..." : "Approve"}
            </button>
        </div>
    );
}

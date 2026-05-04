"use client";

interface ReviewActionBarProps {
    onApprove: () => void;
    onReject: () => void;
    actionLoading: boolean;
    balanceValid: boolean;
}

export function ReviewActionBar({
    onApprove,
    onReject,
    actionLoading,
    balanceValid
}: ReviewActionBarProps) {
    return (
        <div className="flex items-center gap-2">
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
                disabled={actionLoading || !balanceValid}
                className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
                title={!balanceValid ? "Balance validation failed - cannot approve" : ""}
            >
                {actionLoading ? "Processing..." : "Approve"}
            </button>
        </div>
    );
}

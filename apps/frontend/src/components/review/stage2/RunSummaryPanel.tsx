import { InfoHint } from "@/components/ui/InfoHint";

export interface RunSummaryUnresolvedCounts {
    transfer: number;
    duplicate: number;
    anomaly: number;
}

export interface RunSummaryApproval {
    disabled: boolean;
    reason: string;
}

interface RunSummaryPanelProps {
    runId: string | null;
    unresolvedCounts: RunSummaryUnresolvedCounts;
    processingPendingCount: number;
    pendingMatchesCount: number;
    actionLoading: boolean;
    approval: RunSummaryApproval;
    onApproveRun: () => void;
}

export function RunSummaryPanel({
    runId,
    unresolvedCounts,
    processingPendingCount,
    pendingMatchesCount,
    actionLoading,
    approval,
    onApproveRun,
}: RunSummaryPanelProps) {
    return (
        <div className="mb-6 space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-6 gap-4">
                <div className="card p-4">
                    <p className="text-xs uppercase text-muted font-medium">Run ID</p>
                    <p className="mt-1 text-sm font-semibold break-all">{runId}</p>
                </div>
                <div className="card p-4">
                    <p className="text-xs uppercase text-muted font-medium">
                        Unresolved transfers
                        <InfoHint term="transfer_pair" label="Transfer pair" />
                    </p>
                    <p className="mt-1 text-lg font-semibold text-[var(--warning)]">
                        {unresolvedCounts.transfer} unresolved transfer{unresolvedCounts.transfer === 1 ? "" : "s"}
                    </p>
                </div>
                <div className="card p-4">
                    <p className="text-xs uppercase text-muted font-medium">
                        Duplicates
                        <InfoHint term="duplicate" label="Duplicate" />
                    </p>
                    <p className="mt-1 text-lg font-semibold">
                        {unresolvedCounts.duplicate} duplicate{unresolvedCounts.duplicate === 1 ? "" : "s"}
                    </p>
                </div>
                <div className="card p-4">
                    <p className="text-xs uppercase text-muted font-medium">
                        Anomalies
                        <InfoHint term="anomaly" label="Anomaly" />
                    </p>
                    <p className="mt-1 text-lg font-semibold">
                        {unresolvedCounts.anomaly} anomal{unresolvedCounts.anomaly === 1 ? "y" : "ies"}
                    </p>
                </div>
                <div className="card p-4">
                    <p className="text-xs uppercase text-muted font-medium">Processing</p>
                    <p className={`mt-1 text-lg font-semibold ${processingPendingCount > 0 ? "text-[var(--warning)]" : ""}`}>
                        {processingPendingCount} pending
                    </p>
                </div>
                <div className="card p-4">
                    <p className="text-xs uppercase text-muted font-medium">Pending matches</p>
                    <p className="mt-1 text-lg font-semibold">{pendingMatchesCount}</p>
                </div>
            </div>

            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 p-4 rounded-lg border border-[var(--border)] bg-[var(--background-card)]">
                <div>
                    <p className="text-sm font-medium">Run approval gate</p>
                    <p className="text-sm text-muted">
                        Resolve transfer, duplicate, and anomaly checks and clear Processing Account pending transfers before approving current pending matches.
                    </p>
                </div>
                <button
                    type="button"
                    onClick={onApproveRun}
                    disabled={approval.disabled}
                    className="btn-primary disabled:opacity-50 md:min-w-36"
                    title={approval.reason}
                >
                    {actionLoading ? "Processing..." : "Approve Run"}
                </button>
            </div>
        </div>
    );
}

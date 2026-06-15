import { formatAmount } from "@/lib/currency";
import { formatDateDisplay } from "@/lib/date";

import type { PendingMatch } from "./types";

interface PendingMatchesPanelProps {
    matches: PendingMatch[];
    selectedMatches: Set<string>;
    actionLoading: boolean;
    hasUnresolvedChecks: boolean;
    onToggleMatch: (id: string) => void;
    onToggleAll: () => void;
    onBatchReject: () => void;
    onBatchApprove: () => void;
}

export function PendingMatchesPanel({
    matches,
    selectedMatches,
    actionLoading,
    hasUnresolvedChecks,
    onToggleMatch,
    onToggleAll,
    onBatchReject,
    onBatchApprove,
}: PendingMatchesPanelProps) {
    return (
        <div className="card">
            <div className="card-header flex items-center justify-between">
                <h3 className="text-sm font-medium">Pending Matches</h3>
                <div className="flex items-center gap-2">
                    <button
                        type="button"
                        onClick={onToggleAll}
                        className="text-xs text-muted hover:text-[var(--foreground)]"
                    >
                        {matches.length > 0 && matches.every((m) => selectedMatches.has(m.id)) ? "Deselect all" : "Select all"}
                    </button>
                    <span className="text-xs text-muted">{matches.length} total</span>
                </div>
            </div>

            {matches.length === 0 ? (
                <div className="p-8 text-center text-muted">No pending matches</div>
            ) : (
                <>
                    <div data-testid="stage2-mobile-match-list" className="divide-y divide-[var(--border)] md:hidden">
                            {matches.map((match) => (
                                <article
                                    key={match.id}
                                    data-testid={`stage2-mobile-match-card-${match.id}`}
                                    className="space-y-4 p-4"
                                >
                                    <div className="flex items-start gap-3">
                                        <input
                                            type="checkbox"
                                            aria-label={`Select match ${match.id}`}
                                            checked={selectedMatches.has(match.id)}
                                            onChange={() => onToggleMatch(match.id)}
                                            className="mt-1 rounded"
                                        />
                                        <div className="min-w-0 flex-1">
                                            <div className="flex items-start justify-between gap-3">
                                                <div className="min-w-0">
                                                    <p className="text-xs font-medium uppercase text-muted">Description</p>
                                                    <p className="mt-1 break-words text-sm font-medium">
                                                        {match.description || "—"}
                                                    </p>
                                                </div>
                                                <span
                                                    className={`flex-shrink-0 text-sm font-semibold ${
                                                        match.match_score >= 85
                                                            ? "text-[var(--success)]"
                                                            : match.match_score >= 60
                                                              ? "text-[var(--warning)]"
                                                              : "text-[var(--error)]"
                                                    }`}
                                                >
                                                    {match.match_score}
                                                </span>
                                            </div>

                                            <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                                                <div>
                                                    <p className="text-xs font-medium uppercase text-muted">Amount</p>
                                                    <p className="mt-1 font-semibold">
                                                        {match.amount != null ? formatAmount(match.amount, 2) : "—"}
                                                    </p>
                                                </div>
                                                <div>
                                                    <p className="text-xs font-medium uppercase text-muted">Date</p>
                                                    <p className="mt-1 text-muted">
                                                        {match.txn_date ? formatDateDisplay(match.txn_date) : "—"}
                                                    </p>
                                                </div>
                                                <div className="col-span-2">
                                                    <p className="text-xs font-medium uppercase text-muted">Status</p>
                                                    <span className="badge badge-warning mt-1">{match.status}</span>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </article>
                            ))}
                    </div>

                    <div data-testid="stage2-desktop-match-region" className="hidden max-h-[400px] overflow-hidden md:block">
                        <table className="table-fixed border-collapse text-sm" style={{ width: "calc(100% - 4px)" }}>
                            <thead className="sticky top-0 bg-[var(--background)]">
                                <tr className="border-b border-[var(--border)]">
                                    <th className="text-left px-4 py-2 w-8">
                                        <input
                                            type="checkbox"
                                            checked={selectedMatches.size === matches.length && matches.length > 0}
                                            onChange={onToggleAll}
                                            className="rounded"
                                        />
                                    </th>
                                    <th className="text-left px-4 py-2 font-medium w-20">Score</th>
                                    <th className="text-left px-4 py-2 font-medium">Description</th>
                                    <th className="text-right px-4 py-2 font-medium w-28">Amount</th>
                                    <th className="text-left px-4 py-2 font-medium w-28">Date</th>
                                    <th className="text-left px-4 py-2 font-medium w-32">Status</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-[var(--border)]">
                                {matches.map((match) => (
                                    <tr
                                        key={match.id}
                                        className="hover:bg-[var(--background-muted)]/50 cursor-pointer"
                                        onClick={() => onToggleMatch(match.id)}
                                    >
                                        <td className="px-4 py-2">
                                            <input
                                                onClick={(e) => e.stopPropagation()}
                                                type="checkbox"
                                                checked={selectedMatches.has(match.id)}
                                                onChange={(e) => {
                                                    e.stopPropagation();
                                                    onToggleMatch(match.id);
                                                }}
                                                className="rounded"
                                            />
                                        </td>
                                        <td className="px-4 py-2">
                                            <span
                                                className={`font-medium ${
                                                    match.match_score >= 85
                                                        ? "text-[var(--success)]"
                                                        : match.match_score >= 60
                                                          ? "text-[var(--warning)]"
                                                          : "text-[var(--error)]"
                                                }`}
                                            >
                                                {match.match_score}
                                            </span>
                                        </td>
                                        <td className="truncate px-4 py-2 text-muted">
                                            {match.description || "—"}
                                        </td>
                                        <td className="px-4 py-2 text-right font-medium">
                                            {match.amount != null ? formatAmount(match.amount, 2) : "—"}
                                        </td>
                                        <td className="px-4 py-2 text-muted">
                                            {match.txn_date ? formatDateDisplay(match.txn_date) : "—"}
                                        </td>
                                        <td className="px-4 py-2">
                                            <span className="badge badge-warning">{match.status}</span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>

                    <div className="flex flex-col gap-3 border-t border-[var(--border)] p-4 sm:flex-row sm:items-center sm:justify-between">
                        <span className="text-sm text-muted">{selectedMatches.size} selected</span>
                        <div className="grid grid-cols-2 gap-2 sm:flex sm:items-center">
                            <button
                                type="button"
                                onClick={onBatchReject}
                                disabled={actionLoading || selectedMatches.size === 0}
                                className="btn-secondary text-[var(--error)]"
                            >
                                Reject
                            </button>
                            <button
                                type="button"
                                onClick={onBatchApprove}
                                disabled={
                                    actionLoading ||
                                    selectedMatches.size === 0 ||
                                    hasUnresolvedChecks
                                }
                                className="btn-primary disabled:opacity-50"
                                title={
                                    hasUnresolvedChecks
                                        ? "Resolve consistency checks first"
                                        : ""
                                }
                            >
                                {actionLoading ? "Processing..." : "Approve Selected"}
                            </button>
                        </div>
                    </div>
                </>
            )}
        </div>
    );
}

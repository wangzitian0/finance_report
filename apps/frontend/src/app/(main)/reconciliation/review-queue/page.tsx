"use client";

import { useCallback, useEffect, useId, useState, useRef } from "react";
import Link from "next/link";


import { useToast } from "@/components/ui/Toast";
import { apiFetch } from "@/lib/api";
import { formatCurrencyLocale } from "@/lib/currency";
import { formatDateDisplay, formatDateTimeDisplay } from "@/lib/date";

interface ConsistencyCheck {
    id: string;
    check_type: string;
    status: string;
    related_txn_ids: string[];
    details: Record<string, unknown>;
    severity: string;
    resolved_at: string | null;
    resolution_note: string | null;
    created_at: string;
    updated_at: string;
}

interface Stage2Data {
    pending_matches: Array<{
        id: string;
        match_score: number;
        status: string;
        created_at: string | null;
        description?: string;
        amount?: number;
        txn_date?: string;
    }>;
    consistency_checks: ConsistencyCheck[];
    has_unresolved_checks: boolean;
}

export default function Stage2ReviewQueuePage() {
    const { showToast } = useToast();
    const [data, setData] = useState<Stage2Data | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [selectedMatches, setSelectedMatches] = useState<Set<string>>(new Set());
    const [actionLoading, setActionLoading] = useState(false);
    const [resolveDialogOpen, setResolveDialogOpen] = useState(false);
    const [selectedCheck, setSelectedCheck] = useState<ConsistencyCheck | null>(null);
    const [resolveNote, setResolveNote] = useState("");
    const resolveDialogRef = useRef<HTMLDivElement>(null);
    const resolveTitleId = useId();

    const fetchData = useCallback(async () => {
        try {
            const result = await apiFetch<Stage2Data>("/api/statements/stage2/queue");
            setData(result);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to load review queue");
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchData();
    }, [fetchData]);

    useEffect(() => {
        if (!resolveDialogOpen) return;
        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.key === "Escape" && !actionLoading) {
                setResolveDialogOpen(false);
                setSelectedCheck(null);
                setResolveNote("");
            }
        };
        document.addEventListener("keydown", handleKeyDown);
        return () => document.removeEventListener("keydown", handleKeyDown);
    }, [resolveDialogOpen, actionLoading]);

    useEffect(() => {
        if (!resolveDialogOpen) return;
        const dialog = resolveDialogRef.current;
        if (!dialog) return;
        const focusable = dialog.querySelectorAll<HTMLElement>(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        first?.focus();
        const trap = (e: KeyboardEvent) => {
            if (e.key !== "Tab") return;
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last?.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first?.focus();
            }
        };
        dialog.addEventListener("keydown", trap);
        return () => dialog.removeEventListener("keydown", trap);
    }, [resolveDialogOpen]);

    const toggleMatch = (id: string) => {
        setSelectedMatches((prev) => {
            const next = new Set(prev);
            if (next.has(id)) {
                next.delete(id);
            } else {
                next.add(id);
            }
            return next;
        });
    };

    const toggleAll = () => {
        if (!data) return;
        if (selectedMatches.size === data.pending_matches.length) {
            setSelectedMatches(new Set());
        } else {
            setSelectedMatches(new Set(data.pending_matches.map((m) => m.id)));
        }
    };

    const handleBatchApprove = async () => {
        if (data?.has_unresolved_checks) {
            showToast("Resolve consistency checks first", "error");
            return;
        }
        if (selectedMatches.size === 0) return;

        setActionLoading(true);
        try {
            const result = await apiFetch<{ success: boolean; approved_count: number; error?: string }>(
                "/api/statements/batch-approve-matches",
                {
                    method: "POST",
                    body: JSON.stringify({ match_ids: Array.from(selectedMatches) }),
                }
            );
            if (result.success) {
                showToast(`Approved ${result.approved_count} matches`, "success");
                setSelectedMatches(new Set());
                fetchData();
            } else {
                showToast(result.error || "Failed to approve", "error");
            }
        } catch (err) {
            showToast(err instanceof Error ? err.message : "Failed to approve", "error");
        } finally {
            setActionLoading(false);
        }
    };

    const handleBatchReject = async () => {
        if (selectedMatches.size === 0) return;

        setActionLoading(true);
        try {
            const result = await apiFetch<{ success: boolean; rejected_count: number }>(
                "/api/statements/batch-reject-matches",
                {
                    method: "POST",
                    body: JSON.stringify({ match_ids: Array.from(selectedMatches) }),
                }
            );
            if (result.success) {
                showToast(`Rejected ${result.rejected_count} matches`, "success");
                setSelectedMatches(new Set());
                fetchData();
            }
        } catch (err) {
            showToast(err instanceof Error ? err.message : "Failed to reject", "error");
        } finally {
            setActionLoading(false);
        }
    };

    const handleResolveCheck = async (action: string, note?: string) => {
        if (!selectedCheck) return;

        setActionLoading(true);
        try {
            await apiFetch(`/api/statements/consistency-checks/${selectedCheck.id}/resolve`, {
                method: "POST",
                body: JSON.stringify({ action, note }),
            });
            
            const actionLabels: Record<string, string> = {
                approve: "approved",
                reject: "rejected",
                flag: "flagged",
            };
            const label = actionLabels[action] ?? `${action}ed`;
            showToast(`Check ${label}`, "success");
            
            setResolveDialogOpen(false);
            setSelectedCheck(null);
            setResolveNote("");
            fetchData();
        } catch (err) {
            showToast(err instanceof Error ? err.message : "Failed to resolve", "error");
        } finally {
            setActionLoading(false);
        }
    };

    const getSeverityColor = (severity: string) => {
        switch (severity) {
            case "high":
                return "text-[var(--error)]";
            case "medium":
                return "text-[var(--warning)]";
            default:
                return "text-muted";
        }
    };

    const getCheckTypeLabel = (type: string) => {
        switch (type) {
            case "duplicate":
                return "Duplicate";
            case "transfer_pair":
                return "Transfer Pair";
            case "anomaly":
                return "Anomaly";
            default:
                return type;
        }
    };

    if (loading) {
        return (
            <div className="p-6">
                <div className="card p-8 text-center text-muted">
                    <div className="inline-block w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin mb-2" />
                    <p className="text-sm">Loading review queue...</p>
                </div>
            </div>
        );
    }

    if (!data) {
        return (
            <div className="p-6">
                <div className="card p-8 text-center">
                    <p className="text-muted mb-4">Failed to load review queue</p>
                    <button type="button" onClick={fetchData} className="btn-primary">
                        Retry
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className="p-6">
            <div className="mb-6">
                <h1 className="page-title">Reconciliation Review Queue</h1>
                <p className="page-description">
                    Review consistency checks and approve reconciliation matches
                </p>
            </div>

            {error && <div className="mb-4 alert-error">{error}</div>}

            {data.has_unresolved_checks && (
                <div className="mb-4 p-4 border border-[var(--warning)]/30 bg-[var(--warning-muted)] rounded-lg">
                    <div className="flex items-center gap-2">
                        <span className="text-[var(--warning)]">⚠</span>
                        <span className="font-medium text-[var(--warning)]">
                            Unresolved consistency checks block batch approval
                        </span>
                    </div>
                    <p className="text-sm text-muted mt-1">
                        Resolve all checks below before approving matches.
                    </p>
                </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="card">
                    <div className="card-header flex items-center justify-between">
                        <h3 className="text-sm font-medium">Consistency Checks</h3>
                        <span className="text-xs text-muted">{data.consistency_checks.length} pending</span>
                    </div>

                    {data.consistency_checks.length === 0 ? (
                        <div className="p-8 text-center text-muted">No pending checks</div>
                    ) : (
                        <div className="divide-y divide-[var(--border)]">
                            {data.consistency_checks.map((check) => (
                                <div key={check.id} className="p-4 flex items-start justify-between gap-4">
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 mb-1">
                                            <span className={`font-medium ${getSeverityColor(check.severity)}`}>
                                                {check.severity.toUpperCase()}
                                            </span>
                                            <span className="badge badge-muted">{getCheckTypeLabel(check.check_type)}</span>
                                        </div>
                                        <p className="text-sm text-muted truncate">
                                            {(check.details.message as string | undefined) || JSON.stringify(check.details)}
                                        </p>
                                        <p className="text-xs text-muted mt-1">
                                            {formatDateTimeDisplay(check.created_at)}
                                        </p>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => {
                                            setSelectedCheck(check);
                                            setResolveDialogOpen(true);
                                        }}
                                        className="btn-secondary text-sm"
                                    >
                                        Resolve
                                    </button>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                <div className="card">
                    <div className="card-header flex items-center justify-between">
                        <h3 className="text-sm font-medium">Pending Matches</h3>
                        <div className="flex items-center gap-2">
                            <button
                                type="button"
                                onClick={toggleAll}
                                className="text-xs text-muted hover:text-[var(--foreground)]"
                            >
                                {selectedMatches.size === data.pending_matches.length ? "Deselect all" : "Select all"}
                            </button>
                            <span className="text-xs text-muted">{data.pending_matches.length} total</span>
                        </div>
                    </div>

                    {data.pending_matches.length === 0 ? (
                        <div className="p-8 text-center text-muted">No pending matches</div>
                    ) : (
                        <>
                            <div className="overflow-auto max-h-[400px]">
                                <table className="w-full text-sm">
                                    <thead className="sticky top-0 bg-[var(--background)]">
                                        <tr className="border-b border-[var(--border)]">
                                            <th className="text-left px-4 py-2 w-8">
                                                <input
                                                    type="checkbox"
                                                    checked={selectedMatches.size === data.pending_matches.length}
                                                    onChange={toggleAll}
                                                    className="rounded"
                                                />
                                            </th>
                                            <th className="text-left px-4 py-2 font-medium">Score</th>
                                            <th className="text-left px-4 py-2 font-medium">Description</th>
                                            <th className="text-right px-4 py-2 font-medium">Amount</th>
                                            <th className="text-left px-4 py-2 font-medium">Date</th>
                                            <th className="text-left px-4 py-2 font-medium">Status</th>
                                            <th className="text-left px-4 py-2 font-medium">Created</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-[var(--border)]">
                                        {data.pending_matches.map((match) => (
                                            <tr
                                                key={match.id}
                                                className="hover:bg-[var(--background-muted)]/50 cursor-pointer"
                                                onClick={() => toggleMatch(match.id)}
                                            >
                                                <td className="px-4 py-2">
                                                    <input
                                                    onClick={(e) => e.stopPropagation()}
                                                        type="checkbox"
                                                        checked={selectedMatches.has(match.id)}
                                                        onChange={(e) => {
                                                            e.stopPropagation();
                                                            toggleMatch(match.id);
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
                                                <td className="px-4 py-2 text-muted truncate max-w-[200px]">
                                                    {match.description || "—"}
                                                </td>
                                                <td className="px-4 py-2 text-right font-medium">
                                                    {match.amount != null ? formatCurrencyLocale(match.amount, "SGD") : "—"}
                                                </td>
                                                <td className="px-4 py-2 text-muted">
                                                    {match.txn_date ? formatDateDisplay(match.txn_date) : "—"}
                                                </td>
                                                <td className="px-4 py-2">
                                                    <span className="badge badge-warning">{match.status}</span>
                                                </td>
                                                <td className="px-4 py-2 text-muted">
                                                    {match.created_at ? formatDateDisplay(match.created_at) : "—"}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>

                            <div className="p-4 border-t border-[var(--border)] flex items-center justify-between">
                                <span className="text-sm text-muted">{selectedMatches.size} selected</span>
                                <div className="flex items-center gap-2">
                                    <button
                                        type="button"
                                        onClick={handleBatchReject}
                                        disabled={actionLoading || selectedMatches.size === 0}
                                        className="btn-secondary text-[var(--error)]"
                                    >
                                        Reject
                                    </button>
                                    <button
                                        type="button"
                                        onClick={handleBatchApprove}
                                        disabled={
                                            actionLoading ||
                                            selectedMatches.size === 0 ||
                                            data.has_unresolved_checks
                                        }
                                        className="btn-primary disabled:opacity-50"
                                        title={
                                            data.has_unresolved_checks
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
            </div>

{resolveDialogOpen && selectedCheck && (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
        <div className="fixed inset-0 bg-black/60" onClick={() => { if (!actionLoading) { setResolveDialogOpen(false); setSelectedCheck(null); setResolveNote(""); } }} aria-hidden="true" />
        <div ref={resolveDialogRef} role="dialog" aria-modal="true" aria-labelledby={resolveTitleId} className="relative z-10 w-full max-w-md card animate-slide-up">
            <div className="card-header">
                <h2 id={resolveTitleId} className="text-lg font-semibold">Resolve Consistency Check</h2>
            </div>
            <div className="p-6 space-y-4">
                <p className="text-sm text-muted">
                    <span className="font-medium text-[var(--foreground)]">{selectedCheck.severity.toUpperCase()}</span>{" "}
                    {getCheckTypeLabel(selectedCheck.check_type)} —{" "}
                    {(selectedCheck.details.message as string | undefined) || JSON.stringify(selectedCheck.details)}
                </p>
                <div>
                    <label className="block text-sm font-medium mb-1.5">Note (optional)</label>
                    <input
                        type="text"
                        value={resolveNote}
                        onChange={(e) => setResolveNote(e.target.value)}
                        placeholder="Add resolution note..."
                        className="input"
                    />
                </div>
                <div className="flex gap-2 pt-2">
                    <button
                        type="button"
                        onClick={() => { setResolveDialogOpen(false); setSelectedCheck(null); setResolveNote(""); }}
                        className="btn-secondary flex-1"
                        disabled={actionLoading}
                    >
                        Cancel
                    </button>
                    <button
                        type="button"
                        onClick={() => handleResolveCheck("reject", resolveNote)}
                        className="btn-secondary flex-1 text-[var(--error)] border-[var(--error)]/30 hover:bg-[var(--error-muted)]"
                        disabled={actionLoading}
                    >
                        Reject
                    </button>
                    <button
                        type="button"
                        onClick={() => handleResolveCheck("flag", resolveNote)}
                        className="btn-secondary flex-1 text-[var(--warning)] border-[var(--warning)]/30 hover:bg-[var(--warning-muted)]"
                        disabled={actionLoading}
                    >
                        Flag
                    </button>
                    <button
                        type="button"
                        onClick={() => handleResolveCheck("approve", resolveNote)}
                        className="btn-primary flex-1"
                        disabled={actionLoading}
                    >
                        {actionLoading ? "Processing..." : "Approve"}
                    </button>
                </div>
            </div>
        </div>
    </div>
)}
        </div>
    );
}

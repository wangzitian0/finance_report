"use client";

import { useCallback, useEffect, useId, useState, useRef } from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";

import { useFocusTrap } from "@/hooks/useFocusTrap";
import { useToast } from "@/components/ui/Toast";
import { BackLink } from "@/components/ui/BackLink";
import { InfoHint } from "@/components/ui/InfoHint";

import { apiFetch } from "@/lib/api";

import { formatDateDisplay, formatDateTimeDisplay } from "@/lib/date";
import { formatAmount } from "@/lib/currency";
import { ATTENTION_SOURCE_PARAM, ATTENTION_SOURCE_VALUE, isAttentionOrigin } from "@/lib/attentionNavigation";
import type { MoneyValue } from "@/lib/types";

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

interface PendingMatch {
    id: string;
    match_score: number;
    status: string;
    created_at: string | null;
    description?: string;
    amount?: MoneyValue;
    txn_date?: string;
}

interface Stage2Data {
    pending_matches: PendingMatch[];
    consistency_checks: ConsistencyCheck[];
    has_unresolved_checks: boolean;
}

interface ProcessingSummary {
    pending_count: number;
    pending_total: MoneyValue;
    currency: string;
    oldest_pending_date: string | null;
}

export function Stage2ReviewQueue() {
    const { showToast } = useToast();
    const router = useRouter();
    const searchParams = useSearchParams();
    const pathname = usePathname();

    const [data, setData] = useState<Stage2Data | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [selectedMatches, setSelectedMatches] = useState<Set<string>>(new Set());
    const [actionLoading, setActionLoading] = useState(false);
    const [resolveDialogOpen, setResolveDialogOpen] = useState(false);
    const [selectedCheck, setSelectedCheck] = useState<ConsistencyCheck | null>(null);
    const [resolveNote, setResolveNote] = useState("");
    const [processingSummary, setProcessingSummary] = useState<ProcessingSummary | null>(null);
    const resolveDialogRef = useRef<HTMLDivElement>(null);

    // Filters state
    const [checkTypeFilter, setCheckTypeFilter] = useState<string>(searchParams.get("check_type") || "");
    const [statusFilter, setStatusFilter] = useState<string>(searchParams.get("status") || "");
    const [severityFilter, setSeverityFilter] = useState<string[]>(searchParams.get("severity")?.split(",").filter(Boolean) || []);
    const [minScore, setMinScore] = useState<number>(Number(searchParams.get("min_score")) || 0);

    const [filteredChecks, setFilteredChecks] = useState<ConsistencyCheck[] | null>(null);
    const [filtering, setFiltering] = useState(false);
    const resolveTitleId = useId();
    const runIdMatch = pathname.match(/^\/review\/run\/([^/?#]+)/);
    const runId = runIdMatch ? decodeURIComponent(runIdMatch[1]) : null;
    const isRunReview = Boolean(runId);
    const queuePath = runId
        ? `/api/statements/stage2/queue?run_id=${encodeURIComponent(runId)}`
        : "/api/statements/stage2/queue";

    const fetchData = useCallback(async () => {
        try {
            const result = await apiFetch<Stage2Data>(queuePath);
            setData(result);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to load review queue");
        } finally {
            setLoading(false);
        }
    }, [queuePath]);

    useEffect(() => {
        fetchData();
    }, [fetchData]);

    const fetchProcessingSummary = useCallback(async () => {
        if (!isRunReview) return;

        try {
            const result = await apiFetch<ProcessingSummary>("/api/accounts/processing/summary");
            setProcessingSummary(result);
        } catch (err) {
            showToast(err instanceof Error ? err.message : "Failed to load processing summary", "error");
        }
    }, [isRunReview, showToast]);

    useEffect(() => {
        fetchProcessingSummary();
    }, [fetchProcessingSummary]);

    const updateUrlParams = useCallback(() => {
        const params = new URLSearchParams();
        if (isAttentionOrigin(searchParams)) params.set(ATTENTION_SOURCE_PARAM, ATTENTION_SOURCE_VALUE);
        if (checkTypeFilter) params.set("check_type", checkTypeFilter);
        if (statusFilter) params.set("status", statusFilter);
        if (severityFilter.length > 0) params.set("severity", severityFilter.join(","));
        if (minScore > 0) params.set("min_score", minScore.toString());

        const queryString = params.toString();
        router.replace(queryString ? `${pathname}?${queryString}` : pathname, { scroll: false });
    }, [checkTypeFilter, statusFilter, severityFilter, minScore, router, pathname, searchParams]);

    const fetchFilteredChecks = useCallback(async () => {
        setFiltering(true);
        try {
            const params = new URLSearchParams();
            if (checkTypeFilter) params.append("check_type", checkTypeFilter);
            if (statusFilter) params.append("status", statusFilter);
            if (runId) params.append("run_id", runId);
            params.set("limit", "500");

            const result = await apiFetch<{ items: ConsistencyCheck[] }>(`/api/statements/consistency-checks/list?${params.toString()}`);
            const severityFilteredItems =
                severityFilter.length > 0
                    ? result.items.filter((check) => severityFilter.includes(check.severity))
                    : result.items;
            setFilteredChecks(severityFilteredItems);
        } catch (err) {
            showToast(err instanceof Error ? err.message : "Failed to filter checks", "error");
        } finally {
            setFiltering(false);
        }
    }, [checkTypeFilter, statusFilter, severityFilter, runId, showToast]);

    useEffect(() => {
        fetchFilteredChecks();
        updateUrlParams();
    }, [fetchFilteredChecks, updateUrlParams]);

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

    useFocusTrap(resolveDialogRef, resolveDialogOpen);

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
        const visibleIds = data.pending_matches
            .filter((m) => m.match_score >= minScore)
            .map((m) => m.id);
        if (visibleIds.every((id) => selectedMatches.has(id)) && visibleIds.length > 0) {
            setSelectedMatches((prev) => {
                const next = new Set(prev);
                visibleIds.forEach((id) => next.delete(id));
                return next;
            });
        } else {
            setSelectedMatches((prev) => {
                const next = new Set(prev);
                visibleIds.forEach((id) => next.add(id));
                return next;
            });
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
                fetchFilteredChecks();
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
                fetchFilteredChecks();
            }
        } catch (err) {
            showToast(err instanceof Error ? err.message : "Failed to reject", "error");
        } finally {
            setActionLoading(false);
        }
    };

    const handleApproveRun = async () => {
        if (!data) return;

        if (data.has_unresolved_checks) {
            showToast("Resolve consistency checks before approving the run", "error");
            return;
        }

        if ((processingSummary?.pending_count ?? 0) > 0) {
            showToast("Clear Processing Account pending transfers before approving the run", "error");
            return;
        }

        const matchIds = data.pending_matches.map((match) => match.id);
        if (matchIds.length === 0) {
            showToast("No pending matches remain for this run", "success");
            return;
        }

        setActionLoading(true);
        try {
            const result = await apiFetch<{ success: boolean; approved_count: number; error?: string }>(
                "/api/statements/batch-approve-matches",
                {
                    method: "POST",
                    body: JSON.stringify({ match_ids: matchIds, run_id: runId }),
                }
            );
            if (result.success) {
                showToast(`Approved ${result.approved_count} run matches`, "success");
                setSelectedMatches(new Set());
                fetchData();
                fetchFilteredChecks();
                fetchProcessingSummary();
            } else {
                showToast(result.error || "Failed to approve run", "error");
            }
        } catch (err) {
            showToast(err instanceof Error ? err.message : "Failed to approve run", "error");
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
            fetchFilteredChecks();
        } catch (err) {
            showToast(err instanceof Error ? err.message : "Failed to resolve", "error");
        } finally {
            setActionLoading(false);
        }
    };

    const toggleSeverity = (severity: string) => {
        setSeverityFilter(prev =>
            prev.includes(severity)
                ? prev.filter(s => s !== severity)
                : [...prev, severity]
        );
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

    const allChecks = filteredChecks ?? data.consistency_checks;
    const unresolvedChecks = data.consistency_checks.filter((check) => check.status === "pending");
    const unresolvedTransferCount = unresolvedChecks.filter((check) => check.check_type === "transfer_pair").length;
    const unresolvedDuplicateCount = unresolvedChecks.filter((check) => check.check_type === "duplicate").length;
    const unresolvedAnomalyCount = unresolvedChecks.filter((check) => check.check_type === "anomaly").length;
    const matchesFilteredByScore = data.pending_matches.filter(m => m.match_score >= minScore);
    const processingPendingCount = processingSummary?.pending_count ?? 0;
    const approveRunDisabled = actionLoading || data.has_unresolved_checks || processingPendingCount > 0 || data.pending_matches.length === 0;
    const runApprovalTitle = data.has_unresolved_checks
        ? "Resolve consistency checks first"
        : processingPendingCount > 0
          ? "Clear Processing Account pending transfers first"
        : data.pending_matches.length === 0
          ? "No pending matches remain"
          : "Approve all pending matches in this run";

    return (
        <div className="p-6">
            <div className="mb-4">
                <BackLink>Back to Notifications</BackLink>
            </div>
            <div className="mb-6">
                <h1 className="page-title">Review queue</h1>
                <p className="page-description">
                    {isRunReview
                        ? "Matches and checks from this reconciliation run that need a human check before they post."
                        : "Matches and checks that need a human check before they post to your books."}
                </p>
            </div>

            {isRunReview && (
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
                                {unresolvedTransferCount} unresolved transfer{unresolvedTransferCount === 1 ? "" : "s"}
                            </p>
                        </div>
                        <div className="card p-4">
                            <p className="text-xs uppercase text-muted font-medium">
                                Duplicates
                                <InfoHint term="duplicate" label="Duplicate" />
                            </p>
                            <p className="mt-1 text-lg font-semibold">
                                {unresolvedDuplicateCount} duplicate{unresolvedDuplicateCount === 1 ? "" : "s"}
                            </p>
                        </div>
                        <div className="card p-4">
                            <p className="text-xs uppercase text-muted font-medium">
                                Anomalies
                                <InfoHint term="anomaly" label="Anomaly" />
                            </p>
                            <p className="mt-1 text-lg font-semibold">
                                {unresolvedAnomalyCount} anomal{unresolvedAnomalyCount === 1 ? "y" : "ies"}
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
                            <p className="mt-1 text-lg font-semibold">{data.pending_matches.length}</p>
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
                            onClick={handleApproveRun}
                            disabled={approveRunDisabled}
                            className="btn-primary disabled:opacity-50 md:min-w-36"
                            title={runApprovalTitle}
                        >
                            {actionLoading ? "Processing..." : "Approve Run"}
                        </button>
                    </div>
                </div>
            )}

            <div className="mb-6 grid grid-cols-1 md:grid-cols-4 gap-4 bg-[var(--background-card)] p-4 rounded-lg border border-[var(--border)]">
                <div className="space-y-2">
                    <label className="text-xs font-medium text-muted uppercase">Severity</label>
                    <div className="flex flex-wrap gap-2">
                        {["high", "medium", "low"].map(s => (
                            <button
                                key={s}
                                onClick={() => toggleSeverity(s)}
                                className={`px-2 py-1 text-xs rounded-full border transition-colors ${
                                    severityFilter.includes(s)
                                        ? "bg-[var(--accent)] text-white border-[var(--accent)]"
                                        : "bg-[var(--background)] text-muted border-[var(--border)] hover:border-[var(--accent)]"
                                }`}
                            >
                                {s.toUpperCase()}
                            </button>
                        ))}
                    </div>
                </div>

                <div className="space-y-2">
                    <label className="text-xs font-medium text-muted uppercase">Check Type</label>
                    <select
                        className="input text-sm py-1"
                        value={checkTypeFilter}
                        onChange={(e) => setCheckTypeFilter(e.target.value)}
                    >
                        <option value="">All Types</option>
                        <option value="duplicate">Duplicate</option>
                        <option value="transfer_pair">Transfer Pair</option>
                        <option value="anomaly">Anomaly</option>
                    </select>
                </div>

                <div className="space-y-2">
                    <label className="text-xs font-medium text-muted uppercase">Status</label>
                    <select
                        className="input text-sm py-1"
                        value={statusFilter}
                        onChange={(e) => setStatusFilter(e.target.value)}
                    >
                        <option value="">All Statuses</option>
                        <option value="pending">Pending</option>
                        <option value="resolved">Resolved</option>
                    </select>
                </div>

                <div className="space-y-2">
                    <label className="text-xs font-medium text-muted uppercase">
                        Min Match Score: {minScore}
                        <InfoHint term="match_score" label="Match score" />
                    </label>
                    <input
                        type="range"
                        min="0"
                        max="100"
                        step="5"
                        value={minScore}
                        onChange={(e) => setMinScore(parseInt(e.target.value))}
                        className="w-full h-2 bg-[var(--border)] rounded-lg appearance-none cursor-pointer accent-[var(--accent)]"
                    />
                </div>
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

            <div className="grid grid-cols-1 gap-6 2xl:grid-cols-2">
                <div className="card">
                    <div className="card-header flex items-center justify-between">
                        <h3 className="text-sm font-medium">
                            Consistency Checks
                            <InfoHint term="consistency_check" label="Consistency check" />
                        </h3>
                        <span className="text-xs text-muted">{allChecks.length} total</span>
                    </div>

                    {allChecks.length === 0 ? (
                        <div className="p-8 text-center text-muted">No pending checks</div>
                    ) : (
                        <div className="divide-y divide-[var(--border)]">
                            {allChecks.map((check) => (
                                <div key={check.id} className="p-4 flex items-start justify-between gap-4">
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 mb-1">
                                            <span className={`font-medium text-xs ${getSeverityColor(check.severity)}`}>
                                                {check.severity.toUpperCase()}
                                            </span>
                                            <span className="badge badge-muted text-[10px]">{getCheckTypeLabel(check.check_type)}</span>
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
                                {matchesFilteredByScore.length > 0 && matchesFilteredByScore.every((m) => selectedMatches.has(m.id)) ? "Deselect all" : "Select all"}
                            </button>
                            <span className="text-xs text-muted">{matchesFilteredByScore.length} total</span>
                        </div>
                    </div>

                    {matchesFilteredByScore.length === 0 ? (
                        <div className="p-8 text-center text-muted">No pending matches</div>
                    ) : (
                        <>
                            <div data-testid="stage2-mobile-match-list" className="divide-y divide-[var(--border)] md:hidden">
                                    {matchesFilteredByScore.map((match) => (
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
                                                    onChange={() => toggleMatch(match.id)}
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
                                                    checked={selectedMatches.size === matchesFilteredByScore.length && matchesFilteredByScore.length > 0}
                                                    onChange={toggleAll}
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
                                        {matchesFilteredByScore.map((match) => (
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

"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";

import { InfoHint } from "@/components/ui/InfoHint";
import { SmartBackLink } from "@/components/ui/SmartBackLink";
import { useToast } from "@/components/ui/Toast";
import { useFocusTrap } from "@/hooks/useFocusTrap";
import { apiOperation } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-schema";
import { ATTENTION_SOURCE_PARAM, ATTENTION_SOURCE_VALUE, isAttentionOrigin } from "@/lib/attentionNavigation";
import { formatAmount } from "@/lib/audit/money";
import { formatDateDisplay, formatDateTimeDisplay } from "@/lib/date";
import { checkSeverityColor, checkTypeLabel } from "@/lib/statusLabels";
import type { ConsistencyCheck, PendingMatch, ProcessingSummaryResponse, Stage2Data } from "@/lib/types";

const CHECK_TYPES: readonly Schemas["CheckType"][] = ["duplicate", "transfer_pair", "anomaly"];
const CHECK_STATUSES: readonly Schemas["CheckStatus"][] = ["pending", "approved", "rejected", "flagged"];
const checkTypeParameter = (v: string) => CHECK_TYPES.find((c) => c === v);
const checkStatusParameter = (v: string) => CHECK_STATUSES.find((c) => c === v);
const matchScoreColorClass = (s: number) => (s >= 85 ? "text-[var(--success)]" : s >= 60 ? "text-[var(--warning)]" : "text-[var(--error)]");

export interface RunSummaryUnresolvedCounts { transfer: number; duplicate: number; anomaly: number; }
export interface RunSummaryApproval { disabled: boolean; reason: string; }

export function RunSummaryPanel({ runId, unresolvedCounts, processingPendingCount, pendingMatchesCount, actionLoading, approval, onApproveRun }: {
  runId: string | null; unresolvedCounts: RunSummaryUnresolvedCounts; processingPendingCount: number; pendingMatchesCount: number; actionLoading: boolean; approval: RunSummaryApproval; onApproveRun: () => void;
}) {
  return (
    <div className="mb-6 space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-6 gap-4">
        <div className="card p-4"><p className="text-xs uppercase text-muted font-medium">Run ID</p><p className="mt-1 text-sm font-semibold break-all">{runId}</p></div>
        <div className="card p-4"><p className="text-xs uppercase text-muted font-medium">Unresolved transfers<InfoHint term="transfer_pair" label="Transfer pair" /></p><p className="mt-1 text-lg font-semibold text-[var(--warning)]">{unresolvedCounts.transfer} unresolved transfer{unresolvedCounts.transfer === 1 ? "" : "s"}</p></div>
        <div className="card p-4"><p className="text-xs uppercase text-muted font-medium">Duplicates<InfoHint term="duplicate" label="Duplicate" /></p><p className="mt-1 text-lg font-semibold">{unresolvedCounts.duplicate} duplicate{unresolvedCounts.duplicate === 1 ? "" : "s"}</p></div>
        <div className="card p-4"><p className="text-xs uppercase text-muted font-medium">Anomalies<InfoHint term="anomaly" label="Anomaly" /></p><p className="mt-1 text-lg font-semibold">{unresolvedCounts.anomaly} anomal{unresolvedCounts.anomaly === 1 ? "y" : "ies"}</p></div>
        <div className="card p-4"><p className="text-xs uppercase text-muted font-medium">Processing</p><p className={`mt-1 text-lg font-semibold ${processingPendingCount > 0 ? "text-[var(--warning)]" : ""}`}>{processingPendingCount} pending</p></div>
        <div className="card p-4"><p className="text-xs uppercase text-muted font-medium">Pending matches</p><p className="mt-1 text-lg font-semibold">{pendingMatchesCount}</p></div>
      </div>
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 p-4 rounded-lg border border-[var(--border)] bg-[var(--background-card)]">
        <div>
          <p className="text-sm font-medium">Run approval gate</p>
          <p className="text-sm text-muted">Resolve transfer, duplicate, and anomaly checks and clear Processing Account pending transfers before approving current pending matches.</p>
        </div>
        <button type="button" onClick={onApproveRun} disabled={approval.disabled} className="btn-primary disabled:opacity-50 md:min-w-36" title={approval.reason}>{actionLoading ? "Processing..." : "Approve Run"}</button>
      </div>
    </div>
  );
}

export interface Stage2FiltersState { checkType: string; status: string; severity: string[]; minScore: number; }

export function Stage2Filters({ filters, onChange }: { filters: Stage2FiltersState; onChange: (patch: Partial<Stage2FiltersState>) => void }) {
  const toggleSeverity = (s: string) => onChange({ severity: filters.severity.includes(s) ? filters.severity.filter((x) => x !== s) : [...filters.severity, s] });
  return (
    <div className="mb-6 grid grid-cols-1 md:grid-cols-4 gap-4 bg-[var(--background-card)] p-4 rounded-lg border border-[var(--border)]">
      <div className="space-y-2">
        <label className="text-xs font-medium text-muted uppercase">Severity</label>
        <div className="flex flex-wrap gap-2">
          {["high", "medium", "low"].map((s) => (
            <button key={s} type="button" onClick={() => toggleSeverity(s)} className={`px-2 py-1 text-xs rounded-full border transition-colors ${filters.severity.includes(s) ? "bg-[var(--accent)] text-white border-[var(--accent)]" : "bg-[var(--background)] text-muted border-[var(--border)] hover:border-[var(--accent)]"}`}>{s.toUpperCase()}</button>
          ))}
        </div>
      </div>
      <div className="space-y-2">
        <label className="text-xs font-medium text-muted uppercase">Check Type</label>
        <select className="input text-sm py-1" value={filters.checkType} onChange={(e) => onChange({ checkType: e.target.value })}>
          <option value="">All Types</option><option value="duplicate">Duplicate</option><option value="transfer_pair">Transfer Pair</option><option value="anomaly">Anomaly</option>
        </select>
      </div>
      <div className="space-y-2">
        <label className="text-xs font-medium text-muted uppercase">Status</label>
        <select className="input text-sm py-1" value={filters.status} onChange={(e) => onChange({ status: e.target.value })}>
          <option value="">All Statuses</option><option value="pending">Pending</option><option value="resolved">Resolved</option>
        </select>
      </div>
      <div className="space-y-2">
        <label className="text-xs font-medium text-muted uppercase">Min Match Score: {filters.minScore}<InfoHint term="match_score" label="Match score" /></label>
        <input type="range" min="0" max="100" step="5" value={filters.minScore} onChange={(e) => onChange({ minScore: parseInt(e.target.value) })} className="w-full h-2 bg-[var(--border)] rounded-lg appearance-none cursor-pointer accent-[var(--accent)]" />
      </div>
    </div>
  );
}

export function ConsistencyChecksPanel({ checks, onResolve }: { checks: ConsistencyCheck[]; onResolve: (check: ConsistencyCheck) => void }) {
  return (
    <div className="card">
      <div className="card-header flex items-center justify-between">
        <h3 className="text-sm font-medium">Consistency Checks<InfoHint term="consistency_check" label="Consistency check" /></h3>
        <span className="text-xs text-muted">{checks.length} total</span>
      </div>
      {checks.length === 0 ? (
        <div className="p-8 text-center text-muted">No pending checks</div>
      ) : (
        <div className="divide-y divide-[var(--border)]">
          {checks.map((check) => (
            <div key={check.id} className="p-4 flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`font-medium text-xs ${checkSeverityColor(check.severity)}`}>{check.severity.toUpperCase()}</span>
                  <span className="badge badge-muted text-[10px]">{checkTypeLabel(check.check_type)}</span>
                </div>
                <p className="text-sm text-muted truncate">{(check.details.message as string | undefined) || JSON.stringify(check.details)}</p>
                <p className="text-xs text-muted mt-1">{formatDateTimeDisplay(check.created_at)}</p>
              </div>
              <button type="button" onClick={() => onResolve(check)} className="btn-secondary text-sm">Resolve</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function PendingMatchesPanel({ matches, selectedMatches, actionLoading, hasUnresolvedChecks, onToggleMatch, onToggleAll, onBatchReject, onBatchApprove }: {
  matches: PendingMatch[]; selectedMatches: Set<string>; actionLoading: boolean; hasUnresolvedChecks: boolean; onToggleMatch: (id: string) => void; onToggleAll: () => void; onBatchReject: () => void; onBatchApprove: () => void;
}) {
  return (
    <div className="card">
      <div className="card-header flex items-center justify-between">
        <h3 className="text-sm font-medium">Pending Matches</h3>
        <div className="flex items-center gap-2">
          <button type="button" onClick={onToggleAll} className="text-xs text-muted hover:text-[var(--foreground)]">
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
              <article key={match.id} data-testid={`stage2-mobile-match-card-${match.id}`} className="space-y-4 p-4">
                <div className="flex items-start gap-3">
                  <input type="checkbox" aria-label={`Select match ${match.id}`} checked={selectedMatches.has(match.id)} onChange={() => onToggleMatch(match.id)} className="mt-1 rounded" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0"><p className="text-xs font-medium uppercase text-muted">Description</p><p className="mt-1 break-words text-sm font-medium">{match.description || "—"}</p></div>
                      <span className={`flex-shrink-0 text-sm font-semibold ${matchScoreColorClass(match.match_score)}`}>{match.match_score}</span>
                    </div>
                    <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                      <div><p className="text-xs font-medium uppercase text-muted">Amount</p><p className="mt-1 font-semibold">{match.amount != null ? formatAmount(match.amount, 2) : "—"}</p></div>
                      <div><p className="text-xs font-medium uppercase text-muted">Date</p><p className="mt-1 text-muted">{match.txn_date ? formatDateDisplay(match.txn_date) : "—"}</p></div>
                      <div className="col-span-2"><p className="text-xs font-medium uppercase text-muted">Status</p><span className="badge badge-warning mt-1">{match.status}</span></div>
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
                  <th className="text-left px-4 py-2 w-8"><input type="checkbox" aria-label="Select all matches" checked={selectedMatches.size === matches.length && matches.length > 0} onChange={onToggleAll} className="rounded" /></th>
                  <th className="text-left px-4 py-2 font-medium w-20">Score</th>
                  <th className="text-left px-4 py-2 font-medium">Description</th>
                  <th className="text-right px-4 py-2 font-medium w-28">Amount</th>
                  <th className="text-left px-4 py-2 font-medium w-28">Date</th>
                  <th className="text-left px-4 py-2 font-medium w-32">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {matches.map((match) => (
                  <tr key={match.id} className="hover:bg-[var(--background-muted)]/50 cursor-pointer" onClick={() => onToggleMatch(match.id)}>
                    <td className="px-4 py-2"><input onClick={(e) => e.stopPropagation()} type="checkbox" aria-label={`Select match ${match.description || match.id}`} checked={selectedMatches.has(match.id)} onChange={(e) => { e.stopPropagation(); onToggleMatch(match.id); }} className="rounded" /></td>
                    <td className="px-4 py-2"><span className={`font-medium ${matchScoreColorClass(match.match_score)}`}>{match.match_score}</span></td>
                    <td className="truncate px-4 py-2 text-muted">{match.description || "—"}</td>
                    <td className="px-4 py-2 text-right font-medium">{match.amount != null ? formatAmount(match.amount, 2) : "—"}</td>
                    <td className="px-4 py-2 text-muted">{match.txn_date ? formatDateDisplay(match.txn_date) : "—"}</td>
                    <td className="px-4 py-2"><span className="badge badge-warning">{match.status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-col gap-3 border-t border-[var(--border)] p-4 sm:flex-row sm:items-center sm:justify-between">
            <span className="text-sm text-muted">{selectedMatches.size} selected</span>
            <div className="grid grid-cols-2 gap-2 sm:flex sm:items-center">
              <button type="button" onClick={onBatchReject} disabled={actionLoading || selectedMatches.size === 0} className="btn-secondary text-[var(--error)]">Reject</button>
              <button type="button" onClick={onBatchApprove} disabled={actionLoading || selectedMatches.size === 0 || hasUnresolvedChecks} className="btn-primary disabled:opacity-50" title={hasUnresolvedChecks ? "Resolve consistency checks first" : ""}>{actionLoading ? "Processing..." : "Approve Selected"}</button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export function ResolveCheckDialog({ check, actionLoading, onClose, onResolve }: {
  check: ConsistencyCheck; actionLoading: boolean; onClose: () => void; onResolve: (action: string, note?: string) => void;
}) {
  const [resolveNote, setResolveNote] = useState("");
  const resolveDialogRef = useRef<HTMLDivElement>(null);
  const resolveTitleId = useId();

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => { if (e.key === "Escape" && !actionLoading) onClose(); };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [actionLoading, onClose]);

  useFocusTrap(resolveDialogRef, true);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="fixed inset-0 bg-black/60" onClick={() => { if (!actionLoading) onClose(); }} aria-hidden="true" />
      <div ref={resolveDialogRef} role="dialog" aria-modal="true" aria-labelledby={resolveTitleId} className="relative z-10 w-full max-w-md card animate-slide-up">
        <div className="card-header"><h2 id={resolveTitleId} className="text-lg font-semibold">Resolve Consistency Check</h2></div>
        <div className="p-6 space-y-4">
          <p className="text-sm text-muted">
            <span className="font-medium text-[var(--foreground)]">{check.severity.toUpperCase()}</span> {checkTypeLabel(check.check_type)} — {(check.details.message as string | undefined) || JSON.stringify(check.details)}
          </p>
          <div>
            <label htmlFor={`${resolveTitleId}-note`} className="block text-sm font-medium mb-1.5">Note (optional)</label>
            <input id={`${resolveTitleId}-note`} type="text" value={resolveNote} onChange={(e) => setResolveNote(e.target.value)} placeholder="Add resolution note..." className="input" />
          </div>
          <div className="flex gap-2 pt-2">
            <button type="button" onClick={onClose} className="btn-secondary flex-1" disabled={actionLoading}>Cancel</button>
            <button type="button" onClick={() => onResolve("reject", resolveNote)} className="btn-secondary flex-1 text-[var(--error)] border-[var(--error)]/30 hover:bg-[var(--error-muted)]" disabled={actionLoading}>Reject</button>
            <button type="button" onClick={() => onResolve("flag", resolveNote)} className="btn-secondary flex-1 text-[var(--warning)] border-[var(--warning)]/30 hover:bg-[var(--warning-muted)]" disabled={actionLoading}>Flag</button>
            <button type="button" onClick={() => onResolve("approve", resolveNote)} className="btn-primary flex-1" disabled={actionLoading}>{actionLoading ? "Processing..." : "Approve"}</button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function Stage2ReviewQueue({ embedded = false, runId = null }: { embedded?: boolean; runId?: string | null } = {}) {
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
  const [processingSummary, setProcessingSummary] = useState<ProcessingSummaryResponse | null>(null);

  const [checkTypeFilter, setCheckTypeFilter] = useState<string>(searchParams.get("check_type") || "");
  const [statusFilter, setStatusFilter] = useState<string>(searchParams.get("status") || "");
  const [severityFilter, setSeverityFilter] = useState<string[]>(searchParams.get("severity")?.split(",").filter(Boolean) || []);
  const [minScore, setMinScore] = useState<number>(Number(searchParams.get("min_score")) || 0);
  const [filteredChecks, setFilteredChecks] = useState<ConsistencyCheck[] | null>(null);

  const isRunReview = Boolean(runId);

  const fetchData = useCallback(async () => {
    try {
      const result = await apiOperation("get_stage2_review_queue_statements_stage2_queue_get", { query: { run_id: runId } });
      setData(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load review queue");
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const fetchProcessingSummary = useCallback(async () => {
    if (!isRunReview) return;
    try {
      setProcessingSummary(await apiOperation("get_processing_summary_accounts_processing_summary_get"));
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Failed to load processing summary", "error");
    }
  }, [isRunReview, showToast]);

  useEffect(() => { fetchProcessingSummary(); }, [fetchProcessingSummary]);

  const updateUrlParams = useCallback(() => {
    if (embedded) return;
    const params = new URLSearchParams();
    if (isAttentionOrigin(searchParams)) params.set(ATTENTION_SOURCE_PARAM, ATTENTION_SOURCE_VALUE);
    if (checkTypeFilter) params.set("check_type", checkTypeFilter);
    if (statusFilter) params.set("status", statusFilter);
    if (severityFilter.length > 0) params.set("severity", severityFilter.join(","));
    if (minScore > 0) params.set("min_score", minScore.toString());
    const qs = params.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }, [embedded, checkTypeFilter, statusFilter, severityFilter, minScore, router, pathname, searchParams]);

  const fetchFilteredChecks = useCallback(async () => {
    try {
      const result = await apiOperation("list_consistency_checks_statements_consistency_checks_list_get", {
        query: { check_type: checkTypeParameter(checkTypeFilter), status: checkStatusParameter(statusFilter), run_id: runId, limit: 500 },
      });
      setFilteredChecks(severityFilter.length > 0 ? result.items.filter((c) => severityFilter.includes(c.severity)) : result.items);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Failed to filter checks", "error");
    }
  }, [checkTypeFilter, statusFilter, severityFilter, runId, showToast]);

  useEffect(() => { fetchFilteredChecks(); updateUrlParams(); }, [fetchFilteredChecks, updateUrlParams]);

  const toggleMatch = (id: string) => setSelectedMatches((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const toggleAll = () => {
    if (!data) return;
    const visibleIds = data.pending_matches.filter((m) => m.match_score >= minScore).map((m) => m.id);
    setSelectedMatches((prev) => {
      const next = new Set(prev);
      const allSelected = visibleIds.every((id) => prev.has(id)) && visibleIds.length > 0;
      visibleIds.forEach((id) => (allSelected ? next.delete(id) : next.add(id)));
      return next;
    });
  };

  const handleBatchApprove = async () => {
    if (data?.has_unresolved_checks) { showToast("Resolve consistency checks first", "error"); return; }
    if (selectedMatches.size === 0) return;
    setActionLoading(true);
    try {
      const result = await apiOperation("batch_approve_matches_statements_batch_approve_matches_post", { body: { match_ids: Array.from(selectedMatches) } });
      showToast(`Approved ${result.approved_count} matches`, "success");
      setSelectedMatches(new Set());
      fetchData();
      fetchFilteredChecks();
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
      const result = await apiOperation("batch_reject_matches_statements_batch_reject_matches_post", { body: { match_ids: Array.from(selectedMatches) } });
      showToast(`Rejected ${result.rejected_count} matches`, "success");
      setSelectedMatches(new Set());
      fetchData();
      fetchFilteredChecks();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Failed to reject", "error");
    } finally {
      setActionLoading(false);
    }
  };

  const handleApproveRun = async () => {
    if (!data) return;
    if (data.has_unresolved_checks) { showToast("Resolve consistency checks before approving the run", "error"); return; }
    if ((processingSummary?.pending_count ?? 0) > 0) { showToast("Clear Processing Account pending transfers before approving the run", "error"); return; }
    const matchIds = data.pending_matches.map((m) => m.id);
    if (matchIds.length === 0) { showToast("No pending matches remain for this run", "success"); return; }
    setActionLoading(true);
    try {
      const result = await apiOperation("batch_approve_matches_statements_batch_approve_matches_post", { body: { match_ids: matchIds, run_id: runId } });
      showToast(`Approved ${result.approved_count} run matches`, "success");
      setSelectedMatches(new Set());
      fetchData();
      fetchFilteredChecks();
      fetchProcessingSummary();
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
      await apiOperation("resolve_consistency_check_statements_consistency_checks__check_id__resolve_post", { path: { check_id: selectedCheck.id }, body: { action, note } });
      const labels: Record<string, string> = { approve: "approved", reject: "rejected", flag: "flagged" };
      showToast(`Check ${labels[action] ?? `${action}ed`}`, "success");
      setResolveDialogOpen(false);
      setSelectedCheck(null);
      fetchData();
      fetchFilteredChecks();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Failed to resolve", "error");
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return (
      <div className={embedded ? "py-4" : "p-6"}>
        <div className="card p-8 text-center text-muted">
          <div className="inline-block w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin mb-2" />
          <p className="text-sm">Loading review queue...</p>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className={embedded ? "py-4" : "p-6"}>
        <div className="card p-8 text-center">
          <p className="text-muted mb-4">Failed to load review queue</p>
          <button type="button" onClick={fetchData} className="btn-primary">Retry</button>
        </div>
      </div>
    );
  }

  const allChecks = filteredChecks ?? data.consistency_checks;
  const unresolvedChecks = data.consistency_checks.filter((c) => c.status === "pending");
  const matchesFilteredByScore = data.pending_matches.filter((m) => m.match_score >= minScore);
  const processingPendingCount = processingSummary?.pending_count ?? 0;
  const approveRunDisabled = actionLoading || data.has_unresolved_checks || processingPendingCount > 0 || data.pending_matches.length === 0;
  const runApprovalTitle = data.has_unresolved_checks ? "Resolve consistency checks first" : processingPendingCount > 0 ? "Clear Processing Account pending transfers first" : data.pending_matches.length === 0 ? "No pending matches remain" : "Approve all pending matches in this run";

  return (
    <div className={embedded ? "space-y-4" : "p-6"}>
      {!embedded && (
        <>
          <div className="mb-4"><SmartBackLink fallbackHref="/reconciliation" fallbackLabel="Back to Reconciliation" /></div>
          <div className="mb-6">
            <h1 className="page-title">Review queue</h1>
            <p className="page-description">{isRunReview ? "Matches and checks from this reconciliation run that need a human check before they post." : "Matches and checks that need a human check before they post to your books."}</p>
          </div>
        </>
      )}
      {isRunReview && (
        <RunSummaryPanel
          runId={runId}
          unresolvedCounts={{
            transfer: unresolvedChecks.filter((c) => c.check_type === "transfer_pair").length,
            duplicate: unresolvedChecks.filter((c) => c.check_type === "duplicate").length,
            anomaly: unresolvedChecks.filter((c) => c.check_type === "anomaly").length,
          }}
          processingPendingCount={processingPendingCount}
          pendingMatchesCount={data.pending_matches.length}
          actionLoading={actionLoading}
          approval={{ disabled: approveRunDisabled, reason: runApprovalTitle }}
          onApproveRun={handleApproveRun}
        />
      )}
      <Stage2Filters
        filters={{ checkType: checkTypeFilter, status: statusFilter, severity: severityFilter, minScore }}
        onChange={(patch) => {
          if (patch.checkType !== undefined) setCheckTypeFilter(patch.checkType);
          if (patch.status !== undefined) setStatusFilter(patch.status);
          if (patch.severity !== undefined) setSeverityFilter(patch.severity);
          if (patch.minScore !== undefined) setMinScore(patch.minScore);
        }}
      />
      {error && <div className="mb-4 alert-error">{error}</div>}
      {data.has_unresolved_checks && (
        <div className="mb-4 p-4 border border-[var(--warning)]/30 bg-[var(--warning-muted)] rounded-lg">
          <div className="flex items-center gap-2"><span className="text-[var(--warning)]">⚠</span><span className="font-medium text-[var(--warning)]">Unresolved consistency checks block batch approval</span></div>
          <p className="text-sm text-muted mt-1">Resolve all checks below before approving matches.</p>
        </div>
      )}
      <div className="grid grid-cols-1 gap-6 2xl:grid-cols-2">
        <ConsistencyChecksPanel checks={allChecks} onResolve={(check) => { setSelectedCheck(check); setResolveDialogOpen(true); }} />
        <PendingMatchesPanel matches={matchesFilteredByScore} selectedMatches={selectedMatches} actionLoading={actionLoading} hasUnresolvedChecks={data.has_unresolved_checks} onToggleMatch={toggleMatch} onToggleAll={toggleAll} onBatchReject={handleBatchReject} onBatchApprove={handleBatchApprove} />
      </div>
      {resolveDialogOpen && selectedCheck && (
        <ResolveCheckDialog check={selectedCheck} actionLoading={actionLoading} onClose={() => { setResolveDialogOpen(false); setSelectedCheck(null); }} onResolve={handleResolveCheck} />
      )}
    </div>
  );
}

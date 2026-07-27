"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";

import { useToast } from "@/components/ui/Toast";
import { BackLink } from "@/components/ui/BackLink";

import { apiOperation } from "@/lib/api-client";

import {
  ATTENTION_SOURCE_PARAM,
  ATTENTION_SOURCE_VALUE,
  isAttentionOrigin,
} from "@/lib/attentionNavigation";
import type { Schemas } from "@/lib/api-schema";

import { ConsistencyChecksPanel } from "./stage2/ConsistencyChecksPanel";
import { PendingMatchesPanel } from "./stage2/PendingMatchesPanel";
import { ResolveCheckDialog } from "./stage2/ResolveCheckDialog";
import { RunSummaryPanel } from "./stage2/RunSummaryPanel";
import { Stage2Filters } from "./stage2/Stage2Filters";
import type {
  ConsistencyCheck,
  ProcessingSummaryResponse,
  Stage2Data,
} from "@/lib/types";

const CHECK_TYPES: readonly Schemas["CheckType"][] = [
  "duplicate",
  "transfer_pair",
  "anomaly",
];
const CHECK_STATUSES: readonly Schemas["CheckStatus"][] = [
  "pending",
  "approved",
  "rejected",
  "flagged",
];

function checkTypeParameter(value: string): Schemas["CheckType"] | undefined {
  return CHECK_TYPES.find((candidate) => candidate === value);
}

function checkStatusParameter(
  value: string,
): Schemas["CheckStatus"] | undefined {
  return CHECK_STATUSES.find((candidate) => candidate === value);
}

export function Stage2ReviewQueue() {
  const { showToast } = useToast();
  const router = useRouter();
  const searchParams = useSearchParams();
  const pathname = usePathname();

  const [data, setData] = useState<Stage2Data | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedMatches, setSelectedMatches] = useState<Set<string>>(
    new Set(),
  );
  const [actionLoading, setActionLoading] = useState(false);
  const [resolveDialogOpen, setResolveDialogOpen] = useState(false);
  const [selectedCheck, setSelectedCheck] = useState<ConsistencyCheck | null>(
    null,
  );
  const [processingSummary, setProcessingSummary] =
    useState<ProcessingSummaryResponse | null>(null);

  // Filters state
  const [checkTypeFilter, setCheckTypeFilter] = useState<string>(
    searchParams.get("check_type") || "",
  );
  const [statusFilter, setStatusFilter] = useState<string>(
    searchParams.get("status") || "",
  );
  const [severityFilter, setSeverityFilter] = useState<string[]>(
    searchParams.get("severity")?.split(",").filter(Boolean) || [],
  );
  const [minScore, setMinScore] = useState<number>(
    Number(searchParams.get("min_score")) || 0,
  );

  const [filteredChecks, setFilteredChecks] = useState<
    ConsistencyCheck[] | null
  >(null);
  const runIdMatch = pathname.match(/^\/review\/run\/([^/?#]+)/);
  const runId = runIdMatch ? decodeURIComponent(runIdMatch[1]) : null;
  const isRunReview = Boolean(runId);
  const fetchData = useCallback(async () => {
    try {
      const result = await apiOperation(
        "get_stage2_review_queue_statements_stage2_queue_get",
        {
          query: { run_id: runId },
        },
      );
      setData(result);
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load review queue",
      );
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const fetchProcessingSummary = useCallback(async () => {
    if (!isRunReview) return;

    try {
      const result = await apiOperation(
        "get_processing_summary_accounts_processing_summary_get",
      );
      setProcessingSummary(result);
    } catch (err) {
      showToast(
        err instanceof Error
          ? err.message
          : "Failed to load processing summary",
        "error",
      );
    }
  }, [isRunReview, showToast]);

  useEffect(() => {
    fetchProcessingSummary();
  }, [fetchProcessingSummary]);

  const updateUrlParams = useCallback(() => {
    const params = new URLSearchParams();
    if (isAttentionOrigin(searchParams))
      params.set(ATTENTION_SOURCE_PARAM, ATTENTION_SOURCE_VALUE);
    if (checkTypeFilter) params.set("check_type", checkTypeFilter);
    if (statusFilter) params.set("status", statusFilter);
    if (severityFilter.length > 0)
      params.set("severity", severityFilter.join(","));
    if (minScore > 0) params.set("min_score", minScore.toString());

    const queryString = params.toString();
    router.replace(queryString ? `${pathname}?${queryString}` : pathname, {
      scroll: false,
    });
  }, [
    checkTypeFilter,
    statusFilter,
    severityFilter,
    minScore,
    router,
    pathname,
    searchParams,
  ]);

  const fetchFilteredChecks = useCallback(async () => {
    try {
      const result = await apiOperation(
        "list_consistency_checks_statements_consistency_checks_list_get",
        {
          query: {
            check_type: checkTypeParameter(checkTypeFilter),
            status: checkStatusParameter(statusFilter),
            run_id: runId,
            limit: 500,
          },
        },
      );
      const severityFilteredItems =
        severityFilter.length > 0
          ? result.items.filter((check) =>
              severityFilter.includes(check.severity),
            )
          : result.items;
      setFilteredChecks(severityFilteredItems);
    } catch (err) {
      showToast(
        err instanceof Error ? err.message : "Failed to filter checks",
        "error",
      );
    }
  }, [checkTypeFilter, statusFilter, severityFilter, runId, showToast]);

  useEffect(() => {
    fetchFilteredChecks();
    updateUrlParams();
  }, [fetchFilteredChecks, updateUrlParams]);

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
    if (
      visibleIds.every((id) => selectedMatches.has(id)) &&
      visibleIds.length > 0
    ) {
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
      const result = await apiOperation(
        "batch_approve_matches_statements_batch_approve_matches_post",
        {
          body: { match_ids: Array.from(selectedMatches) },
        },
      );
      // #1001: a 2xx means success; failures (e.g. unresolved checks → 409)
      // throw ApiError and are surfaced in the catch below.
      showToast(`Approved ${result.approved_count} matches`, "success");
      setSelectedMatches(new Set());
      fetchData();
      fetchFilteredChecks();
    } catch (err) {
      showToast(
        err instanceof Error ? err.message : "Failed to approve",
        "error",
      );
    } finally {
      setActionLoading(false);
    }
  };

  const handleBatchReject = async () => {
    if (selectedMatches.size === 0) return;

    setActionLoading(true);
    try {
      const result = await apiOperation(
        "batch_reject_matches_statements_batch_reject_matches_post",
        {
          body: { match_ids: Array.from(selectedMatches) },
        },
      );
      showToast(`Rejected ${result.rejected_count} matches`, "success");
      setSelectedMatches(new Set());
      fetchData();
      fetchFilteredChecks();
    } catch (err) {
      showToast(
        err instanceof Error ? err.message : "Failed to reject",
        "error",
      );
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
      showToast(
        "Clear Processing Account pending transfers before approving the run",
        "error",
      );
      return;
    }

    const matchIds = data.pending_matches.map((match) => match.id);
    if (matchIds.length === 0) {
      showToast("No pending matches remain for this run", "success");
      return;
    }

    setActionLoading(true);
    try {
      const result = await apiOperation(
        "batch_approve_matches_statements_batch_approve_matches_post",
        {
          body: { match_ids: matchIds, run_id: runId },
        },
      );
      showToast(`Approved ${result.approved_count} run matches`, "success");
      setSelectedMatches(new Set());
      fetchData();
      fetchFilteredChecks();
      fetchProcessingSummary();
    } catch (err) {
      showToast(
        err instanceof Error ? err.message : "Failed to approve run",
        "error",
      );
    } finally {
      setActionLoading(false);
    }
  };

  const handleResolveCheck = async (action: string, note?: string) => {
    if (!selectedCheck) return;

    setActionLoading(true);
    try {
      await apiOperation(
        "resolve_consistency_check_statements_consistency_checks__check_id__resolve_post",
        {
          path: { check_id: selectedCheck.id },
          body: { action, note },
        },
      );

      const actionLabels: Record<string, string> = {
        approve: "approved",
        reject: "rejected",
        flag: "flagged",
      };
      const label = actionLabels[action] ?? `${action}ed`;
      showToast(`Check ${label}`, "success");

      setResolveDialogOpen(false);
      setSelectedCheck(null);
      fetchData();
      fetchFilteredChecks();
    } catch (err) {
      showToast(
        err instanceof Error ? err.message : "Failed to resolve",
        "error",
      );
    } finally {
      setActionLoading(false);
    }
  };

  const closeResolveDialog = () => {
    setResolveDialogOpen(false);
    setSelectedCheck(null);
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
  const unresolvedChecks = data.consistency_checks.filter(
    (check) => check.status === "pending",
  );
  const unresolvedTransferCount = unresolvedChecks.filter(
    (check) => check.check_type === "transfer_pair",
  ).length;
  const unresolvedDuplicateCount = unresolvedChecks.filter(
    (check) => check.check_type === "duplicate",
  ).length;
  const unresolvedAnomalyCount = unresolvedChecks.filter(
    (check) => check.check_type === "anomaly",
  ).length;
  const matchesFilteredByScore = data.pending_matches.filter(
    (match) => match.match_score >= minScore,
  );
  const processingPendingCount = processingSummary?.pending_count ?? 0;
  const approveRunDisabled =
    actionLoading ||
    data.has_unresolved_checks ||
    processingPendingCount > 0 ||
    data.pending_matches.length === 0;
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
        <RunSummaryPanel
          runId={runId}
          unresolvedCounts={{
            transfer: unresolvedTransferCount,
            duplicate: unresolvedDuplicateCount,
            anomaly: unresolvedAnomalyCount,
          }}
          processingPendingCount={processingPendingCount}
          pendingMatchesCount={data.pending_matches.length}
          actionLoading={actionLoading}
          approval={{ disabled: approveRunDisabled, reason: runApprovalTitle }}
          onApproveRun={handleApproveRun}
        />
      )}

      <Stage2Filters
        filters={{
          checkType: checkTypeFilter,
          status: statusFilter,
          severity: severityFilter,
          minScore,
        }}
        onChange={(patch) => {
          if (patch.checkType !== undefined)
            setCheckTypeFilter(patch.checkType);
          if (patch.status !== undefined) setStatusFilter(patch.status);
          if (patch.severity !== undefined) setSeverityFilter(patch.severity);
          if (patch.minScore !== undefined) setMinScore(patch.minScore);
        }}
      />

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
        <ConsistencyChecksPanel
          checks={allChecks}
          onResolve={(check) => {
            setSelectedCheck(check);
            setResolveDialogOpen(true);
          }}
        />

        <PendingMatchesPanel
          matches={matchesFilteredByScore}
          selectedMatches={selectedMatches}
          actionLoading={actionLoading}
          hasUnresolvedChecks={data.has_unresolved_checks}
          onToggleMatch={toggleMatch}
          onToggleAll={toggleAll}
          onBatchReject={handleBatchReject}
          onBatchApprove={handleBatchApprove}
        />
      </div>

      {resolveDialogOpen && selectedCheck && (
        <ResolveCheckDialog
          check={selectedCheck}
          actionLoading={actionLoading}
          onClose={closeResolveDialog}
          onResolve={handleResolveCheck}
        />
      )}
    </div>
  );
}

"use client";

import { Alert, Badge } from "@/components/ui";
import { useApiQuery } from "@/hooks/useApiQuery";
import { formatCurrencyLocale } from "@/lib/audit/money";
import { formatDateDisplay } from "@/lib/date";
import { SHARED_STALE_MS, STATEMENT_COVERAGE_QUERY_KEY } from "@/lib/sharedQueries";

const ISSUE_LABELS: Record<string, string> = {
  gap: "Gap",
  overlap: "Overlap",
  duplicate_period: "Duplicate period",
  opening_balance_mismatch: "Opening balance mismatch",
};

/**
 * Per-account statement continuity and staleness summary for the upload workspace.
 */
export function StatementCoverageCard() {
  const coverage = useApiQuery(
    STATEMENT_COVERAGE_QUERY_KEY,
    "list_statement_coverage_statements_coverage_get",
    {},
    { staleTime: SHARED_STALE_MS },
  );

  if (coverage.isError) {
    return (
      <Alert variant="error" className="mb-6">
        {coverage.error?.message ?? "Failed to load statement coverage"}
      </Alert>
    );
  }

  const items = coverage.data?.items ?? [];
  if (items.length === 0) return null;

  return (
    <section id="statement-coverage" aria-label="Statement coverage" className="card mb-6 overflow-hidden">
      <div className="card-header flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium">Statement Coverage</h3>
        <span className="text-xs text-muted">
          {items.length} {items.length === 1 ? "account" : "accounts"}
          {coverage.data?.as_of ? ` · as of ${formatDateDisplay(coverage.data.as_of)}` : ""}
        </span>
      </div>
      <div className="divide-y divide-[var(--border)]">
        {items.map((account) => {
          const hasIssues = account.issues.length > 0;
          return (
            <div key={account.account_id} className="px-4 py-3 sm:px-6 flex flex-col gap-1.5 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-sm truncate">{account.account_name}</span>
                  <span className="text-xs text-muted">
                    {account.cadence === "daily_snapshot" ? "Daily snapshot" : "Monthly"} · {account.currency}
                  </span>
                </div>
                <div className="text-xs text-muted mt-0.5">
                  {account.latest_source_date
                    ? `Latest confirmed: ${formatDateDisplay(account.latest_source_date)}`
                    : "No confirmed statement yet"}
                  {account.latest_confirmed_balance != null
                    ? ` · Balance ${formatCurrencyLocale(account.latest_confirmed_balance, account.currency)}`
                    : ""}
                </div>
                {hasIssues && (
                  <div className="text-xs text-[var(--warning)] mt-1">
                    {account.issues
                      .map((issue) => `${ISSUE_LABELS[issue.type] ?? issue.type} (${formatDateDisplay(issue.period_start)} – ${formatDateDisplay(issue.period_end)})`)
                      .join(" · ")}
                  </div>
                )}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {hasIssues ? (
                  <Badge variant="warning">
                    {account.issues.length} {account.issues.length === 1 ? "issue" : "issues"}
                  </Badge>
                ) : account.is_stale ? (
                  <Badge variant="warning">Stale</Badge>
                ) : (
                  <Badge variant="success">Up to date</Badge>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

import { infiniteQueryOptions, useInfiniteQuery } from "@tanstack/react-query";

import { apiOperation } from "@/lib/api-client";
import { formatCurrencyLocale } from "@/lib/audit/money";
import { formatDateDisplay } from "@/lib/date";
import { SHARED_STALE_MS } from "@/lib/sharedQueries";
import { countLabel } from "@/lib/statusLabels";
import type { CashFlowLine, CashFlowLineEventsPage } from "@/lib/types";

// The cash-flow statement carries an event count for each line (#2583 S10). The events of a
// line load page by page when the user opens the line. This component mounts only for an open
// line, so a closed line never issues a request. Each page request runs the cash-flow builder
// again, so a page holds 200 events and the open and reopened line share one cache entry.

/** Page size of the line events. The backend maximum is 500. */
export const CASH_FLOW_LINE_EVENTS_PAGE_SIZE = 200;

export interface CashFlowPeriod {
  start_date: string;
  end_date: string;
  currency: string;
}

/** The accessible name of a line: its description holds the direction and the counterparts. */
export function cashFlowLineLabel(line: CashFlowLine): string {
  return line.description || line.subcategory;
}

function nextOffset(page: CashFlowLineEventsPage): number | undefined {
  const next = page.offset + page.limit;
  return next < page.total ? next : undefined;
}

/** The one cache entry of the events of a line. The "report" key prefix is ledger-derived. */
export function cashFlowLineEventsQueryOptions(period: CashFlowPeriod, lineId: string) {
  return infiniteQueryOptions({
    queryKey: ["report", "cash-flow", "line-events", period.start_date, period.end_date, period.currency, lineId] as const,
    queryFn: ({ pageParam, signal }) =>
      apiOperation("list_cash_flow_line_events_reports_cash_flow_line_events_get", {
        query: { ...period, line_id: lineId, limit: CASH_FLOW_LINE_EVENTS_PAGE_SIZE, offset: pageParam },
        signal,
      }),
    initialPageParam: 0,
    getNextPageParam: nextOffset,
    staleTime: SHARED_STALE_MS,
  });
}

/** The events of one open cash-flow line, with the amounts in the report currency. */
export function CashFlowLineEvents({ period, line }: { period: CashFlowPeriod; line: CashFlowLine }) {
  const query = useInfiniteQuery(cashFlowLineEventsQueryOptions(period, line.line_id));
  const events = query.data?.pages.flatMap((page) => page.events ?? []) ?? [];
  const total = query.data?.pages[0]?.total ?? line.event_count;

  return (
    <section
      id={`cash-flow-events-${line.line_id}`}
      aria-label={`Events for ${cashFlowLineLabel(line)}`}
      className="mt-2 rounded-md border border-[var(--border)] p-2"
    >
      <p className="text-xs font-medium">{`${events.length} of ${countLabel(total, "event")}`}</p>
      {query.isLoading ? (
        <p role="status" className="mt-1 text-xs text-muted">
          Loading events...
        </p>
      ) : null}
      {events.length > 0 ? (
        <ul className="mt-1 max-h-64 space-y-1 overflow-y-auto pr-1">
          {events.map((event) => (
            <li key={`${event.journal_entry_id}-${event.reason_code ?? ""}`} className="flex justify-between gap-2 text-xs">
              <span className="min-w-0">
                <span className="text-muted">{formatDateDisplay(event.entry_date)}</span>{" "}
                <span className="break-words">{event.memo}</span>
              </span>
              <span className="shrink-0 font-medium">{formatCurrencyLocale(event.amount, period.currency)}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {query.error ? (
        <p className="mt-1 text-xs text-[var(--error)]">
          {query.error instanceof Error ? query.error.message : "Failed to load the events."}
        </p>
      ) : null}
      {query.hasNextPage ? (
        <button
          type="button"
          className="btn-secondary mt-2 text-xs"
          disabled={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          {query.isFetchingNextPage ? "Loading..." : "Load more events"}
        </button>
      ) : null}
    </section>
  );
}

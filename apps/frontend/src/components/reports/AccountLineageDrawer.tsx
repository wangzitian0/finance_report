"use client";

import { useEffect, useState } from "react";

import { LineagePanel } from "@/components/reports/LineagePanel";
import Sheet from "@/components/ui/Sheet";
import { apiFetch } from "@/lib/api";
import { formatCurrencyLocale } from "@/lib/money";
import { anchorFromTypedIdentifier, type LineageAnchor } from "@/lib/lineage";
import type { AccountLineageResponse } from "@/lib/types";

export interface AccountLineageTarget {
  accountId: string;
  accountName: string;
  /** Report end date (YYYY-MM-DD). */
  asOfDate: string;
  /** Period start (YYYY-MM-DD) for period reports like the income statement. */
  startDate?: string;
  currency: string;
}

interface DrawerState {
  isLoading: boolean;
  error: string | null;
  response: AccountLineageResponse | null;
}

const EMPTY: DrawerState = { isLoading: false, error: null, response: null };

function accountLineageUrl(target: AccountLineageTarget): string {
  const params = new URLSearchParams({
    account_id: target.accountId,
    as_of_date: target.asOfDate,
    currency: target.currency,
  });
  if (target.startDate) params.set("start_date", target.startDate);
  return `/api/reports/account-lineage?${params.toString()}`;
}

/**
 * Two-step report drill-down (EPIC-022 AC22.3.4/AC22.3.5). Clicking an amount
 * opens this drawer listing the journal lines that make up that account's
 * balance; selecting a line opens the full evidence lineage for that line.
 */
export function AccountLineageDrawer({
  target,
  onClose,
}: {
  target: AccountLineageTarget | null;
  onClose: () => void;
}) {
  const [state, setState] = useState<DrawerState>(EMPTY);
  const [anchor, setAnchor] = useState<LineageAnchor | null>(null);
  const [anchorTitle, setAnchorTitle] = useState("");

  const targetKey = target ? `${target.accountId}:${target.asOfDate}:${target.startDate ?? ""}:${target.currency}` : null;

  useEffect(() => {
    // Reset any selected lineage line whenever the target changes or closes,
    // so the nested LineagePanel never lingers with stale state.
    setAnchor(null);
    if (!target) {
      setState(EMPTY);
      return;
    }
    let active = true;
    setState({ isLoading: true, error: null, response: null });
    apiFetch<AccountLineageResponse>(accountLineageUrl(target))
      .then((response) => {
        if (active) setState({ isLoading: false, error: null, response });
      })
      .catch((err: unknown) => {
        if (active) {
          setState({
            isLoading: false,
            error: err instanceof Error ? err.message : "Failed to load contributing transactions",
            response: null,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [target, targetKey]);

  const { isLoading, error, response } = state;

  return (
    <>
      <Sheet
        isOpen={target !== null}
        onClose={onClose}
        title={target ? `Sources · ${target.accountName}` : "Sources"}
        width="max-w-lg"
      >
        <div className="space-y-3">
          {isLoading && (
            <p className="text-sm text-muted" role="status">
              Loading contributing transactions…
            </p>
          )}

          {error && <div className="alert-error text-sm">{error}</div>}

          {!isLoading && !error && response && (
            response.lines.length === 0 ? (
              <p className="text-sm text-muted">No source transactions contribute to this balance yet.</p>
            ) : (
              <ul className="divide-y divide-[var(--border)]" aria-label="Contributing transactions">
                {response.lines.map((line) => (
                  <li key={line.journal_line_id}>
                    <button
                      type="button"
                      className="flex w-full items-center justify-between gap-3 px-1 py-3 text-left text-sm hover:bg-[var(--background-muted)]/50"
                      onClick={() => {
                        setAnchor(anchorFromTypedIdentifier(`journal_line:${line.journal_line_id}`));
                        setAnchorTitle(line.memo || "Journal line");
                      }}
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-medium">{line.memo || "Journal line"}</span>
                        <span className="block text-xs text-muted">{line.entry_date}</span>
                      </span>
                      <span className="shrink-0 font-medium tabular-nums">
                        {formatCurrencyLocale(line.amount, response.currency)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )
          )}
        </div>
      </Sheet>

      <LineagePanel anchor={anchor} title={anchorTitle} onClose={() => setAnchor(null)} />
    </>
  );
}

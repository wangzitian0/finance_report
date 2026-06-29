"use client";

import Link from "next/link";

import type { FxWarning } from "@/lib/types";

const DEFAULT_MESSAGE =
  "Activity is recorded without an opening balance, so account totals reflect only " +
  "period movement, not your actual starting balances. Record opening balances to trust these totals.";

interface OpeningBalanceWarningBannerProps {
  warnings?: FxWarning[];
}

/**
 * #1481/#1486: surfaces the backend `opening_balance_warnings` on the reporting
 * and dashboard surfaces (not just the Accounts page), so a structurally
 * incomplete total is never presented as trusted with no guidance. The CTA opens
 * the guided opening-balance flow on the Accounts page (#949).
 */
export function OpeningBalanceWarningBanner({ warnings }: OpeningBalanceWarningBannerProps) {
  if (!warnings?.length) return null;
  const message = warnings.find((warning) => warning.message)?.message ?? DEFAULT_MESSAGE;

  return (
    <div
      role="alert"
      className="mb-6 rounded-md border border-[var(--warning)]/40 bg-[var(--warning-muted)] p-4 text-sm"
    >
      <p className="font-medium text-[var(--warning)]">Opening balances not recorded</p>
      <p className="mt-1 text-muted">{message}</p>
      <Link
        href="/accounts"
        className="mt-2 inline-flex items-center gap-1 font-medium text-[var(--warning)] hover:underline"
      >
        Set opening balances →
      </Link>
    </div>
  );
}

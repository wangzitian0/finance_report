"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { AccountLineageDrawer, ExcludedHoldingsNote, type AccountLineageTarget } from "@/components/reports/AccountLineageDrawer";
import { SkeletonBlock } from "@/components/ui";
import { useBaseCurrency } from "@/hooks/useBaseCurrency";
import { useCurrencies } from "@/hooks/useCurrencies";
import {
  REPORT_PERIOD_PRESETS,
  reportsHref,
  type ReportFilters,
  type ReportTab,
  type UseReportFiltersResult,
} from "@/hooks/useReportFilters";
import { useStatementCockpit } from "@/hooks/useStatementCockpit";
import { apiOperationDownload, type ApiOperationRequest } from "@/lib/api-client";
import { compareAmounts, formatCurrencyLocale, subtractAmounts, toDecimal, type MonetaryInput } from "@/lib/audit/money";
import { formatPercentFromPercentValue, percentNumberFromParts } from "@/lib/audit/ratio/format";
import { formatDateDisplay } from "@/lib/date";
import { reportAccountDisplayName } from "@/lib/statusLabels";
import type { FxWarning, ReportLine } from "@/lib/types";

/**
 * The dimension bar of Home and of every `/reports` tab (#2621 LC, #2548 P1).
 *
 * One bar sets the period preset, steps to the previous or next period, sets a custom period,
 * and sets the currency. `showScope` adds the restricted-holdings scope where a balance sheet shows.
 * The bar writes only the URL (`useReportFilters`), so a link reproduces the view.
 * When the coverage start bounds the default view, a note under the bar states the start, names
 * the cash accounts that set it, and links to the opening balances (#2646).
 */
export function ReportDimensionBar({
  filters,
  showScope = false,
}: {
  filters: UseReportFiltersResult;
  showScope?: boolean;
}) {
  const { currencies } = useCurrencies();
  const { baseCurrency } = useBaseCurrency();
  const currency = filters.currency ?? baseCurrency;
  const currencyChoices = currencies.includes(currency) ? currencies : [currency, ...currencies];
  const stepClass =
    "inline-flex h-8 w-8 items-center justify-center rounded border border-[var(--border)] text-muted hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40";

  return (
    <div className="space-y-1.5">
      <div role="group" aria-label="Report dimensions" className="flex flex-wrap items-center gap-2 text-sm">
        <div role="group" aria-label="Reporting period" className="inline-flex items-center gap-0.5 rounded-lg bg-[var(--background-muted)] p-1">
          {REPORT_PERIOD_PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              aria-label={`Period ${preset}`}
              aria-pressed={filters.preset === preset}
              onClick={() => filters.setPreset(preset)}
              className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                filters.preset === preset
                  ? "bg-[var(--background-card)] text-[var(--foreground)] shadow-sm"
                  : "text-muted hover:text-[var(--foreground)]"
              }`}
            >
              {preset}
            </button>
          ))}
          <button
            type="button"
            aria-label="Custom period"
            aria-pressed={filters.preset === null}
            // The default view waits for its coverage start: a custom period copies the shown dates.
            disabled={!filters.ready}
            onClick={() => filters.setCustomPeriod(filters.startDate, filters.endDate)}
            className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
              filters.preset === null
                ? "bg-[var(--background-card)] text-[var(--foreground)] shadow-sm"
                : "text-muted hover:text-[var(--foreground)]"
            }`}
          >
            Custom
          </button>
        </div>
        {filters.preset === null ? (
          <div className="inline-flex items-center gap-1">
            <input
              type="date"
              aria-label="Period start"
              value={filters.startDate}
              max={filters.endDate}
              onChange={(event) => {
                const start = event.target.value;
                if (start) filters.setCustomPeriod(start, start > filters.endDate ? start : filters.endDate);
              }}
              className="input h-8 w-auto py-0 text-xs"
            />
            <span aria-hidden="true" className="text-muted">–</span>
            <input
              type="date"
              aria-label="Period end"
              value={filters.endDate}
              min={filters.startDate}
              onChange={(event) => {
                const end = event.target.value;
                if (end) filters.setCustomPeriod(end < filters.startDate ? end : filters.startDate, end);
              }}
              className="input h-8 w-auto py-0 text-xs"
            />
          </div>
        ) : (
          <div className="inline-flex items-center gap-1">
            <button
              type="button"
              aria-label="Previous period"
              // While the default view waits for the coverage start, the previous period is not known.
              disabled={!filters.ready || filters.previousEnd === null}
              onClick={() => filters.goToPeriodEnd(filters.previousEnd!)}
              className={stepClass}
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
            </button>
            <span data-testid="report-period-range" aria-live="polite" className="min-w-[11rem] text-center text-xs font-medium tabular-nums">
              {/* The coverage start can move the start: the range waits for it (#2646). */}
              {filters.ready ? `${formatDateDisplay(filters.startDate)} – ${formatDateDisplay(filters.endDate)}` : "…"}
            </span>
            <button
              type="button"
              aria-label="Next period"
              disabled={filters.nextEnd === null}
              onClick={() => filters.goToPeriodEnd(filters.nextEnd!)}
              className={stepClass}
            >
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        )}
        <select
          aria-label="Reporting currency"
          value={currency}
          onChange={(event) => filters.setCurrency(event.target.value)}
          className="input h-8 w-auto py-0 text-xs"
        >
          {currencyChoices.map((code) => (
            <option key={code} value={code}>
              {code}
            </option>
          ))}
        </select>
        {showScope && (
          <label className="inline-flex items-center gap-1.5 text-xs text-muted">
            <input
              type="checkbox"
              checked={filters.includeRestricted}
              onChange={(event) => filters.setIncludeRestricted(event.target.checked)}
            />
            Include restricted holdings
          </label>
        )}
      </div>
      {filters.ready && filters.opensAtCoverageStart && (
        <p data-testid="report-coverage-note" className="text-xs text-muted">
          {coverageNote(filters.startDate, filters.coverageLimitingAccounts)}{" "}
          <Link href="/settings?tab=accounts" className="font-medium text-[var(--accent)] hover:underline">
            Add an opening balance
          </Link>
        </p>
      )}
      {filters.ready && filters.latestStatementEnd && (
        <div
          data-testid="report-latest-statement-banner"
          role="status"
          className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-[var(--warning)]/40 bg-[var(--warning-muted)] px-3 py-2 text-xs text-[var(--foreground)]"
        >
          <span>{`Latest statement ends ${formatDateDisplay(filters.latestStatementEnd)}, before this period.`}</span>
          <button
            type="button"
            onClick={() => filters.goToPeriodEnd(filters.latestStatementEnd!)}
            className="rounded bg-[var(--warning)]/15 px-2.5 py-1 font-semibold text-[var(--warning)] hover:bg-[var(--warning)]/25"
          >
            {`Jump to ${formatDateDisplay(filters.latestStatementEnd)}`}
          </button>
        </div>
      )}
    </div>
  );
}

/** The text of the coverage note: the start and the accounts with no earlier opening balance. */
export function coverageNote(startDate: string, accounts: readonly string[]): string {
  const names =
    accounts.length === 0
      ? "Your cash accounts have"
      : accounts.length === 1
        ? `${accounts[0]} has`
        : `${accounts.slice(0, -1).join(", ")} and ${accounts[accounts.length - 1]} have`;
  return `Starts ${formatDateDisplay(startDate)}: ${names} no opening balance before this date.`;
}

function formatWarning(warning: FxWarning): string {
  if (warning.message) return warning.message;
  const from = warning.base_currency ?? warning.from_currency;
  const to = warning.quote_currency ?? warning.to_currency;
  const route = from && to ? `${from} to ${to}` : "FX conversion";
  const when = warning.rate_date ?? warning.date;
  const date = when ? ` on ${when}` : "";
  const fallback = warning.fallback_date ? `; using ${warning.fallback_date}` : "";
  return `${warning.type}: ${route}${date}${fallback}`;
}

export function FxWarningBanner({ warnings }: { warnings?: FxWarning[] }) {
  if (!warnings?.length) return null;
  return (
    <div className="mb-6 rounded-md border border-[var(--warning)]/40 bg-[var(--warning-muted)] p-4 text-sm">
      <p className="font-medium text-[var(--warning)]">Partial FX data used</p>
      <ul className="mt-2 space-y-1 text-muted">
        {warnings.map((w) => (
          <li key={formatWarning(w)}>{formatWarning(w)}</li>
        ))}
      </ul>
    </div>
  );
}

const DEFAULT_OPENING_MSG =
  "Activity is recorded without an opening balance, so account totals reflect only period movement, not your actual starting balances. Record opening balances to trust these totals.";

function formatOpeningBalanceWarning(warning: FxWarning): string | null {
  const account = warning.account_name?.trim() || warning.account?.trim();
  const msg = warning.message?.trim();
  if (account && msg) {
    return msg.includes(account) ? msg : `${account}: ${msg}`;
  }
  if (account) {
    return warning.earliest_activity_date
      ? `${account} has no opening balance before ${warning.earliest_activity_date}.`
      : `${account} has no opening balance recorded.`;
  }
  return msg || null;
}

export function OpeningBalanceWarningBanner({ warnings }: { warnings?: FxWarning[] }) {
  if (!warnings?.length) return null;
  const distinctMessages = Array.from(
    new Set(warnings.map(formatOpeningBalanceWarning).filter((m): m is string => Boolean(m))),
  );
  const messages = distinctMessages.length > 0 ? distinctMessages : [DEFAULT_OPENING_MSG];
  return (
    <div role="alert" className="mb-6 rounded-md border border-[var(--warning)]/40 bg-[var(--warning-muted)] p-4 text-sm">
      <p className="font-medium text-[var(--warning)]">Opening balances not recorded</p>
      {messages.length === 1 ? (
        <p className="mt-1 text-muted">{messages[0]}</p>
      ) : (
        <ul className="mt-1 list-disc space-y-1 pl-5 text-muted">
          {messages.map((msg) => (
            <li key={msg}>{msg}</li>
          ))}
        </ul>
      )}
      <Link href="/settings?tab=accounts" className="mt-2 inline-flex items-center gap-1 font-medium text-[var(--warning)] hover:underline">
        Set opening balances →
      </Link>
    </div>
  );
}

export function ExportCsvButton({ request }: { request: ApiOperationRequest<"export_report_reports_export_get"> }) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleExport = async () => {
    setDownloading(true);
    setError(null);
    try {
      const { blob, filename } = await apiOperationDownload("export_report_reports_export_get", request);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename || "report.csv";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to export CSV.");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="flex flex-col gap-1">
      <button type="button" onClick={handleExport} disabled={downloading} className="btn-secondary text-sm">
        {downloading ? "Exporting..." : "Export CSV"}
      </button>
      {error && <span className="text-xs text-[var(--error)]">{error}</span>}
    </div>
  );
}

export function AiPromptAction({ prompt, label = "AI Interpretation" }: { prompt: string; label?: string }) {
  return (
    <Link href={`/chat?prompt=${encodeURIComponent(prompt)}`} className="btn-secondary text-sm">
      {label}
    </Link>
  );
}

export function ReportToolbar({
  aiPrompt,
  exportControl,
  children,
}: {
  aiPrompt: string;
  exportControl?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {children}
      <AiPromptAction prompt={aiPrompt} />
      {exportControl}
    </div>
  );
}

export function ReportPageSkeleton({ label, sections = 3 }: { label: string; sections?: number }) {
  return (
    <div role="status" aria-label={label} aria-live="polite" aria-busy="true">
      <div className="mb-8 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between" aria-hidden="true">
        <div className="space-y-2">
          <SkeletonBlock className="h-7 w-48" />
          <SkeletonBlock className="h-4 w-72 max-w-full" />
        </div>
        <div className="flex gap-2">
          <SkeletonBlock className="h-9 w-32" />
          <SkeletonBlock className="h-9 w-20" />
          <SkeletonBlock className="h-9 w-28" />
        </div>
      </div>
      <div className="mb-6 flex flex-wrap gap-3" aria-hidden="true">
        <SkeletonBlock className="h-16 w-36" />
        <SkeletonBlock className="h-16 w-36" />
        <SkeletonBlock className="h-16 w-28" />
      </div>
      <div className="mb-6 grid gap-4 md:grid-cols-3" aria-hidden="true">
        {Array.from({ length: 3 }).map((_, idx) => (
          <div key={idx} className="card p-5">
            <SkeletonBlock className="mb-3 h-3 w-24" />
            <SkeletonBlock className="h-7 w-32" />
          </div>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-3" aria-hidden="true">
        {Array.from({ length: sections }).map((_, sIdx) => (
          <div key={sIdx} className="card p-5">
            <SkeletonBlock className="mb-4 h-5 w-36" />
            <div className="space-y-3">
              {Array.from({ length: 4 }).map((__, rIdx) => (
                <div key={rIdx} className="flex items-center justify-between gap-4 rounded-control bg-surface-muted/50 p-2">
                  <SkeletonBlock className="h-4 w-2/5" />
                  <SkeletonBlock className="h-4 w-24" />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ReportPageShell({
  title,
  description,
  toolbar,
  loadingLabel,
  loadingSections,
  isLoading = false,
  isError = false,
  errorMessage,
  onRetry,
  children,
}: {
  title: string;
  description?: string;
  toolbar?: ReactNode;
  loadingLabel: string;
  loadingSections?: number;
  isLoading?: boolean;
  isError?: boolean;
  errorMessage?: string;
  onRetry?: () => void;
  children: ReactNode;
}) {
  if (isLoading) return <ReportPageSkeleton label={loadingLabel} sections={loadingSections} />;
  if (isError) {
    return (
      <div className="card p-8 text-center max-w-md mx-auto">
        <p className="text-muted mb-4">{errorMessage ?? "Failed to load report."}</p>
        {onRetry && <button type="button" onClick={onRetry} className="btn-secondary">Retry</button>}
      </div>
    );
  }
  return (
    <section aria-label={title}>
      <div className="mb-6 flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold">{title}</h2>
          {description && <p className="text-sm text-muted">{description}</p>}
        </div>
        {toolbar}
      </div>
      {children}
    </section>
  );
}

/**
 * The three-statement cockpit of Home and of the `/reports` Overview (#2621 LC, #2548 P1).
 *
 * Each card shows the live metrics of the dimension-bar period and links to its `/reports` tab.
 * When drill-down rows exist, the segmented control selects one statement: on a phone only that
 * card shows, and on every screen the rows below are the largest lines of that statement. When
 * all statements have zero drill-down rows, the switcher is omitted (#2730). A row opens the
 * AccountLineageDrawer with the source transactions of its account.
 */

type StatementId = "balance" | "income" | "cash";

const STATEMENTS: ReadonlyArray<{ id: StatementId; label: string; short: string; tab: ReportTab }> = [
  { id: "balance", label: "Balance sheet", short: "Balance", tab: "balance-sheet" },
  { id: "income", label: "Income statement", short: "Income", tab: "income-statement" },
  { id: "cash", label: "Cash flow", short: "Cash", tab: "cash-flow" },
];

/** The number of statement lines that the drill-down list shows. */
const DRILL_ROW_COUNT = 6;
const WHOLE_UNITS = { maximumFractionDigits: 0 } as const;

const money = (value: MonetaryInput, currency: string) => formatCurrencyLocale(value, currency, "en-US", WHOLE_UNITS);
const signedMoney = (value: MonetaryInput, currency: string) =>
  `${toDecimal(value).isPositive() && !toDecimal(value).isZero() ? "+" : ""}${money(value, currency)}`;

interface DrillRow {
  /** Unique in its statement: a cash-flow line id, or an account id. */
  key: string;
  accountId: string;
  name: string;
  amount: string;
  sourceType?: ReportLine["allocation_source_type"];
}

function largestRows(rows: DrillRow[]): DrillRow[] {
  return rows
    .filter((row) => !toDecimal(row.amount).isZero())
    .sort((a, b) => compareAmounts(toDecimal(b.amount).abs(), toDecimal(a.amount).abs()))
    .slice(0, DRILL_ROW_COUNT);
}

function Metric({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={`font-semibold tabular-nums ${tone}`}>{value}</dd>
    </div>
  );
}

export function StatementCockpit({ filters }: { filters: ReportFilters }) {
  const { balanceSheet, openingBalanceSheet, incomeStatement, cashFlow, pending, error, retry } = useStatementCockpit(filters);
  const [active, setActive] = useState<StatementId>("balance");
  const [lineageTarget, setLineageTarget] = useState<AccountLineageTarget | null>(null);

  const netWorth = balanceSheet ? subtractAmounts(balanceSheet.total_assets, balanceSheet.total_liabilities) : null;
  const openingNetWorth = openingBalanceSheet
    ? subtractAmounts(openingBalanceSheet.total_assets, openingBalanceSheet.total_liabilities)
    : null;
  const savingsRate =
    incomeStatement && toDecimal(incomeStatement.total_income).greaterThan(0)
      ? formatPercentFromPercentValue(
          String(percentNumberFromParts(incomeStatement.net_income, incomeStatement.total_income, { dp: 0 })),
          { dp: 0 },
        )
      : "—";

  const metrics: Record<StatementId, ReactNode> = {
    balance: netWorth && balanceSheet && (
      <>
        <Metric label={filters.includeRestricted ? "Net worth" : "Liquid net worth"} value={money(netWorth, balanceSheet.currency)} />
        <Metric
          label="Change in period"
          value={openingNetWorth ? signedMoney(netWorth.minus(openingNetWorth), balanceSheet.currency) : "—"}
        />
        <Metric label="Total assets" value={money(balanceSheet.total_assets, balanceSheet.currency)} />
        <Metric label="Total liabilities" value={money(balanceSheet.total_liabilities, balanceSheet.currency)} />
      </>
    ),
    income: incomeStatement && (
      <>
        <Metric label="Income" value={money(incomeStatement.total_income, incomeStatement.currency)} tone="text-[var(--success)]" />
        <Metric label="Expenses" value={money(incomeStatement.total_expenses, incomeStatement.currency)} tone="text-[var(--error)]" />
        <Metric label="Net income" value={signedMoney(incomeStatement.net_income, incomeStatement.currency)} />
        <Metric label="Savings rate" value={savingsRate} />
      </>
    ),
    cash: cashFlow && (
      <>
        <Metric label="Operating" value={signedMoney(cashFlow.summary.operating_activities, cashFlow.currency)} />
        <Metric label="Investing" value={signedMoney(cashFlow.summary.investing_activities, cashFlow.currency)} />
        <Metric label="Financing" value={signedMoney(cashFlow.summary.financing_activities, cashFlow.currency)} />
        <Metric label="Net change" value={signedMoney(cashFlow.summary.net_cash_flow, cashFlow.currency)} />
      </>
    ),
  };
  const isPending: Record<StatementId, boolean> = {
    balance: pending.balanceSheet,
    income: pending.incomeStatement,
    cash: pending.cashFlow,
  };

  const rowsByStatement: Record<StatementId, DrillRow[]> = {
    balance: largestRows(
      [...(balanceSheet?.assets ?? []), ...(balanceSheet?.liabilities ?? [])].map((line) => ({
        key: line.account_id,
        accountId: line.account_id,
        name: reportAccountDisplayName(line.name),
        amount: String(line.amount),
        sourceType: line.allocation_source_type ?? (line.provenance === "manual" ? "manual_valuation" : undefined),
      })),
    ),
    income: largestRows(
      [...(incomeStatement?.income ?? []), ...(incomeStatement?.expenses ?? [])].map((line) => ({
        key: line.account_id,
        accountId: line.account_id,
        name: line.name,
        amount: String(line.amount),
      })),
    ),
    cash: largestRows(
      [...(cashFlow?.operating ?? []), ...(cashFlow?.investing ?? []), ...(cashFlow?.financing ?? [])].flatMap((line) =>
        // One counterpart account can have an inflow line and an outflow line: the line id and the
        // description (it names the direction) tell them apart.
        line.account_id
          ? [{ key: line.line_id, accountId: line.account_id, name: line.description || line.subcategory, amount: String(line.amount) }]
          : [],
      ),
    ),
  };
  const rowCurrency: Record<StatementId, string | undefined> = {
    balance: balanceSheet?.currency,
    income: incomeStatement?.currency,
    cash: cashFlow?.currency,
  };
  const activeRows = rowsByStatement[active];
  const activeCurrency = rowCurrency[active] ?? "";
  const hasAnyRows =
    rowsByStatement.balance.length > 0 || rowsByStatement.income.length > 0 || rowsByStatement.cash.length > 0;

  const openLineage = (row: DrillRow) => {
    if (row.sourceType === "manual_valuation") return;
    setLineageTarget({
      accountId: row.accountId,
      accountName: row.name,
      asOfDate: filters.endDate,
      // A balance is a position at the period end. Income and cash flow lines cover the period.
      startDate: active === "balance" ? undefined : filters.startDate,
      currency: activeCurrency,
    });
  };

  return (
    <section aria-label="Three-statement cockpit" className="space-y-3">
      <OpeningBalanceWarningBanner warnings={balanceSheet?.opening_balance_warnings} />
      {error && (
        <div role="alert" className="card flex flex-wrap items-center justify-between gap-2 p-3 text-sm">
          <span>{`Statements unavailable: ${error}`}</span>
          <button type="button" onClick={retry} className="btn-secondary text-sm">
            Retry
          </button>
        </div>
      )}
      {hasAnyRows && (
        <div role="tablist" aria-label="Statement switcher" className="inline-flex rounded-md bg-[var(--background-muted)] p-0.5">
          {STATEMENTS.map((statement) => (
            <button
              key={statement.id}
              type="button"
              role="tab"
              aria-selected={active === statement.id}
              onClick={() => setActive(statement.id)}
              className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
                active === statement.id
                  ? "bg-[var(--background-card)] text-[var(--foreground)] shadow-sm"
                  : "text-muted hover:text-[var(--foreground)]"
              }`}
            >
              {statement.short}
            </button>
          ))}
        </div>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {STATEMENTS.map((statement) => (
          <article
            key={statement.id}
            data-testid={`cockpit-card-${statement.tab}`}
            aria-label={statement.label}
            className={`card p-4 ${!hasAnyRows || active === statement.id ? "" : "hidden sm:block"}`}
          >
            <div className="mb-2 flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">{statement.label}</h3>
              <Link
                href={reportsHref(statement.tab, filters.dimensionQuery)}
                aria-label={`Open the ${statement.label.toLowerCase()} report`}
                className="text-xs text-[var(--accent)] hover:underline"
              >
                Open ↗
              </Link>
            </div>
            {isPending[statement.id] ? (
              <p role="status" className="text-xs text-muted">
                Loading…
              </p>
            ) : metrics[statement.id] ? (
              <>
                <dl className="space-y-1.5 text-sm">{metrics[statement.id]}</dl>
                {statement.id === "balance" && balanceSheet && (
                  <ExcludedHoldingsNote rows={balanceSheet.excluded_holdings} currency={balanceSheet.currency} formatMoney={money} />
                )}
                {statement.id === "balance" && filters.opensAtCoverageStart && filters.openingDate && (
                  // #2646: the period starts on the cash coverage start. The last cash opening balance
                  // posts on that day, so the change starts at the end of that day.
                  <p data-testid="change-in-period-basis" className="mt-2 text-[11px] text-muted">
                    {`Change in period is measured from the end of ${formatDateDisplay(filters.openingDate)}, when your cash opening balances are complete.`}
                  </p>
                )}
              </>
            ) : (
              <p className="text-xs text-muted">No data for this period.</p>
            )}
          </article>
        ))}
      </div>
      {activeRows.length > 0 && (
        <div className="card p-3">
          <p className="mb-2 text-xs text-muted">Largest lines. Select a line to see its source transactions.</p>
          <ul className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
            {activeRows.map((row) => (
              <li key={row.key}>
                {row.sourceType === "manual_valuation" ? (
                  <Link
                    href="/portfolio?panel=evidence"
                    aria-label={`View valuation evidence for ${row.name}`}
                    className="flex w-full items-center justify-between gap-2 rounded-md border border-[var(--border)] px-3 py-2 text-left text-xs hover:border-[var(--accent)]"
                  >
                    <span className="truncate">{row.name}</span>
                    <span className="shrink-0 font-medium tabular-nums">{money(row.amount, activeCurrency)} ›</span>
                  </Link>
                ) : (
                  <button
                    type="button"
                    aria-label={`View source transactions for ${row.name}`}
                    onClick={() => openLineage(row)}
                    className="flex w-full items-center justify-between gap-2 rounded-md border border-[var(--border)] px-3 py-2 text-left text-xs hover:border-[var(--accent)]"
                  >
                    <span className="truncate">{row.name}</span>
                    <span className="shrink-0 font-medium tabular-nums">{money(row.amount, activeCurrency)} ›</span>
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      <AccountLineageDrawer target={lineageTarget} onClose={() => setLineageTarget(null)} />
    </section>
  );
}

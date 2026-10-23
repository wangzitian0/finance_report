"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";

import { AccountLineageDrawer, type AccountLineageTarget } from "@/components/reports/AccountLineageDrawer";
import { ExcludedHoldingsNote } from "@/components/reports/ExcludedHoldingsNote";
import { OpeningBalanceWarningBanner } from "@/components/reports/ReportPageShell";
import { reportsHref, type ReportFilters, type ReportTab } from "@/hooks/useReportFilters";
import { useStatementCockpit } from "@/hooks/useStatementCockpit";
import { formatDateDisplay } from "@/lib/date";
import { compareAmounts, formatCurrencyLocale, subtractAmounts, toDecimal, type MonetaryInput } from "@/lib/audit/money";
import { formatPercentFromPercentValue, percentNumberFromParts } from "@/lib/audit/ratio/format";

/**
 * The three-statement cockpit of Home and of the `/reports` Overview (#2621 LC, #2548 P1).
 *
 * Each card shows the live metrics of the dimension-bar period and links to its `/reports` tab.
 * The segmented control selects one statement: on a phone only that card shows, and on every
 * screen the rows below are the largest lines of that statement. A row opens the
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
        name: line.name,
        amount: String(line.amount),
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

  const openLineage = (row: DrillRow) =>
    setLineageTarget({
      accountId: row.accountId,
      accountName: row.name,
      asOfDate: filters.endDate,
      // A balance is a position at the period end. Income and cash flow lines cover the period.
      startDate: active === "balance" ? undefined : filters.startDate,
      currency: activeCurrency,
    });

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
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {STATEMENTS.map((statement) => (
          <article
            key={statement.id}
            data-testid={`cockpit-card-${statement.tab}`}
            aria-label={statement.label}
            className={`card p-4 ${active === statement.id ? "" : "hidden sm:block"}`}
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
                <button
                  type="button"
                  aria-label={`View source transactions for ${row.name}`}
                  onClick={() => openLineage(row)}
                  className="flex w-full items-center justify-between gap-2 rounded-md border border-[var(--border)] px-3 py-2 text-left text-xs hover:border-[var(--accent)]"
                >
                  <span className="truncate">{row.name}</span>
                  <span className="shrink-0 font-medium tabular-nums">{money(row.amount, activeCurrency)} ›</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <AccountLineageDrawer target={lineageTarget} onClose={() => setLineageTarget(null)} />
    </section>
  );
}

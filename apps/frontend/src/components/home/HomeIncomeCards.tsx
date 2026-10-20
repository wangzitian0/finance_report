"use client";

import Link from "next/link";
import { formatDateDisplay, formatMonthLabel } from "@/lib/date";
import { formatCurrencyLocale, toDecimal } from "@/lib/audit/money";
import type {
  AnnualizedIncomeResponse,
  IncomeStatementResponse,
  RestrictedHolding,
} from "@/lib/types";

interface HomeIncomeCardsProps {
  annualizedIncome: AnnualizedIncomeResponse | null;
  restrictedHoldings: RestrictedHolding[];
  incomeStatement: IncomeStatementResponse | null;
}

export function HomeIncomeCards({
  annualizedIncome,
  restrictedHoldings,
  incomeStatement,
}: HomeIncomeCardsProps) {
  return (
    <>
      <div className="grid gap-3 lg:grid-cols-2 mb-3">
        <div className="card p-3">
          <p className="text-xs text-muted uppercase tracking-wide">
            Annualized Income
          </p>
          <p className="text-xl font-semibold mt-0.5">
            {annualizedIncome
              ? formatCurrencyLocale(
                  annualizedIncome.annualized_total,
                  annualizedIncome.currency,
                  "en-US",
                  { maximumFractionDigits: 0 },
                )
              : "—"}
          </p>
          <p className="text-xs text-muted mt-0.5">
            As of{" "}
            {annualizedIncome?.as_of
              ? formatDateDisplay(annualizedIncome.as_of)
              : "—"}
          </p>
          <div className="mt-2 grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
            <div>
              <p className="text-xs text-muted">Salary</p>
              <p className="font-medium">
                {annualizedIncome
                  ? formatCurrencyLocale(
                      annualizedIncome.annualized_salary,
                      annualizedIncome.currency,
                      "en-US",
                      { maximumFractionDigits: 0 },
                    )
                  : "—"}
              </p>
            </div>
            <div>
              <p className="text-xs text-muted">Bonus</p>
              <p className="font-medium">
                {annualizedIncome
                  ? formatCurrencyLocale(
                      annualizedIncome.annualized_bonus,
                      annualizedIncome.currency,
                      "en-US",
                      { maximumFractionDigits: 0 },
                    )
                  : "—"}
              </p>
            </div>
            <div>
              <p className="text-xs text-muted">Dividend</p>
              <p className="font-medium">
                {annualizedIncome
                  ? formatCurrencyLocale(
                      annualizedIncome.annualized_dividend,
                      annualizedIncome.currency,
                      "en-US",
                      { maximumFractionDigits: 0 },
                    )
                  : "—"}
              </p>
            </div>
          </div>
        </div>
        <div className="card p-3">
          <p className="text-xs text-muted uppercase tracking-wide">
            Restricted Holdings
          </p>
          {restrictedHoldings.length ? (
            <div className="mt-2 space-y-1.5">
              {restrictedHoldings.map((holding) => (
                <div
                  key={`${holding.ticker}-${holding.unlock_date ?? "locked"}`}
                  className="flex items-center justify-between gap-2 rounded-md bg-[var(--background-muted)] p-2 text-xs"
                >
                  <div>
                    <p className="font-medium">{holding.ticker}</p>
                    <p
                      className="text-xs text-muted"
                      title={holding.vesting_schedule ?? undefined}
                    >
                      Unlock{" "}
                      {holding.unlock_date
                        ? formatDateDisplay(holding.unlock_date)
                        : "TBD"}
                    </p>
                  </div>
                  <p className="font-semibold">
                    {formatCurrencyLocale(
                      holding.fair_value,
                      holding.currency,
                      "en-US",
                      { maximumFractionDigits: 0 },
                    )}
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-2 text-xs text-muted">
              No restricted holdings.
            </p>
          )}
        </div>
      </div>

      {/* This Month KPI Cards */}
      {incomeStatement &&
        incomeStatement.trends &&
        incomeStatement.trends.length > 0 &&
        (() => {
          const latest =
            incomeStatement.trends[incomeStatement.trends.length - 1];
          const monthIncome = toDecimal(latest.total_income);
          const monthExpense = toDecimal(latest.total_expenses);
          const monthNet = monthIncome.minus(monthExpense);
          const currency = incomeStatement.currency;
          const fmtOpts = { maximumFractionDigits: 0 } as const;
          return (
            <div className="grid gap-3 md:grid-cols-3 mb-3">
              <Link
                href="/reports/income-statement"
                className="card p-3 hover:border-[var(--accent)] transition-colors cursor-pointer block"
              >
                <p className="text-xs text-muted uppercase tracking-wide">
                  This Month — Income
                </p>
                <p className="text-xl font-semibold text-[var(--success)] mt-0.5">
                  {formatCurrencyLocale(
                    monthIncome,
                    currency,
                    "en-US",
                    fmtOpts,
                  )}
                </p>
                <p className="text-xs text-muted mt-0.5">
                  {formatMonthLabel(latest.period_start)}
                </p>
              </Link>
              <Link
                href="/reports/income-statement"
                className="card p-3 hover:border-[var(--accent)] transition-colors cursor-pointer block"
              >
                <p className="text-xs text-muted uppercase tracking-wide">
                  This Month — Expenses
                </p>
                <p className="text-xl font-semibold text-[var(--error)] mt-0.5">
                  {formatCurrencyLocale(
                    monthExpense,
                    currency,
                    "en-US",
                    fmtOpts,
                  )}
                </p>
                <p className="text-xs text-muted mt-0.5">Total outflows</p>
              </Link>
              <Link
                href="/reports/income-statement"
                className="card p-3 hover:border-[var(--accent)] transition-colors cursor-pointer block"
              >
                <p className="text-xs text-muted uppercase tracking-wide">
                  This Month — Net
                </p>
                <p
                  className={`text-xl font-semibold mt-0.5 ${monthNet.isNegative() ? "text-[var(--error)]" : "text-[var(--success)]"}`}
                >
                  {formatCurrencyLocale(
                    monthNet,
                    currency,
                    "en-US",
                    fmtOpts,
                  )}
                </p>
                <p className="text-xs text-muted mt-0.5">
                  {monthNet.isNegative() ? "Deficit" : "Surplus"}
                </p>
              </Link>
            </div>
          );
        })()}

      {/* Fallback to Period P&L KPI Cards when trends are empty but period figures exist */}
      {incomeStatement &&
        (!incomeStatement.trends || incomeStatement.trends.length === 0) &&
        (!toDecimal(incomeStatement.total_income).isZero() ||
          !toDecimal(incomeStatement.total_expenses).isZero()) &&
        (() => {
          const totalIncome = toDecimal(incomeStatement.total_income);
          const totalExpense = toDecimal(incomeStatement.total_expenses);
          const netIncome = toDecimal(incomeStatement.net_income);
          const currency = incomeStatement.currency;
          const fmtOpts = { maximumFractionDigits: 0 } as const;
          return (
            <div className="grid gap-3 md:grid-cols-3 mb-3" data-testid="period-pnl-summary">
              <Link
                href="/reports/income-statement"
                className="card p-3 hover:border-[var(--accent)] transition-colors cursor-pointer block"
              >
                <p className="text-xs text-muted uppercase tracking-wide">
                  Period — Income
                </p>
                <p className="text-xl font-semibold text-[var(--success)] mt-0.5">
                  {formatCurrencyLocale(totalIncome, currency, "en-US", fmtOpts)}
                </p>
                <p className="text-xs text-muted mt-0.5">Total revenue</p>
              </Link>
              <Link
                href="/reports/income-statement"
                className="card p-3 hover:border-[var(--accent)] transition-colors cursor-pointer block"
              >
                <p className="text-xs text-muted uppercase tracking-wide">
                  Period — Expenses
                </p>
                <p className="text-xl font-semibold text-[var(--error)] mt-0.5">
                  {formatCurrencyLocale(totalExpense, currency, "en-US", fmtOpts)}
                </p>
                <p className="text-xs text-muted mt-0.5">Total outflows</p>
              </Link>
              <Link
                href="/reports/income-statement"
                className="card p-3 hover:border-[var(--accent)] transition-colors cursor-pointer block"
              >
                <p className="text-xs text-muted uppercase tracking-wide">
                  Period — Net
                </p>
                <p
                  className={`text-xl font-semibold mt-0.5 ${netIncome.isNegative() ? "text-[var(--error)]" : "text-[var(--success)]"}`}
                >
                  {formatCurrencyLocale(netIncome, currency, "en-US", fmtOpts)}
                </p>
                <p className="text-xs text-muted mt-0.5">
                  {netIncome.isNegative() ? "Deficit" : "Surplus"}
                </p>
              </Link>
            </div>
          );
        })()}
    </>
  );
}

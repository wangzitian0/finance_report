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
      <div className="grid gap-4 lg:grid-cols-2 mb-6">
        <div className="card p-5">
          <p className="text-xs text-muted uppercase tracking-wide">
            Annualized Income
          </p>
          <p className="text-2xl font-semibold mt-1">
            {annualizedIncome
              ? formatCurrencyLocale(
                  annualizedIncome.annualized_total,
                  annualizedIncome.currency,
                  "en-US",
                  { maximumFractionDigits: 0 },
                )
              : "—"}
          </p>
          <p className="text-xs text-muted mt-1">
            As of{" "}
            {annualizedIncome?.as_of
              ? formatDateDisplay(annualizedIncome.as_of)
              : "—"}
          </p>
          <div className="mt-4 grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
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
        <div className="card p-5">
          <p className="text-xs text-muted uppercase tracking-wide">
            Restricted Holdings
          </p>
          {restrictedHoldings.length ? (
            <div className="mt-3 space-y-2">
              {restrictedHoldings.map((holding) => (
                <div
                  key={`${holding.ticker}-${holding.unlock_date ?? "locked"}`}
                  className="flex items-center justify-between gap-3 rounded-md bg-[var(--background-muted)] p-3 text-sm"
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
            <p className="mt-3 text-sm text-muted">
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
            <div className="grid gap-4 md:grid-cols-3 mb-6">
              <Link
                href="/reports/income-statement"
                className="card p-5 hover:border-[var(--accent)] transition-colors cursor-pointer block"
              >
                <p className="text-xs text-muted uppercase tracking-wide">
                  This Month — Income
                </p>
                <p className="text-2xl font-semibold text-[var(--success)] mt-1">
                  {formatCurrencyLocale(
                    monthIncome,
                    currency,
                    "en-US",
                    fmtOpts,
                  )}
                </p>
                <p className="text-xs text-muted mt-1">
                  {formatMonthLabel(latest.period_start)}
                </p>
              </Link>
              <Link
                href="/reports/income-statement"
                className="card p-5 hover:border-[var(--accent)] transition-colors cursor-pointer block"
              >
                <p className="text-xs text-muted uppercase tracking-wide">
                  This Month — Expenses
                </p>
                <p className="text-2xl font-semibold text-[var(--error)] mt-1">
                  {formatCurrencyLocale(
                    monthExpense,
                    currency,
                    "en-US",
                    fmtOpts,
                  )}
                </p>
                <p className="text-xs text-muted mt-1">Total outflows</p>
              </Link>
              <Link
                href="/reports/income-statement"
                className="card p-5 hover:border-[var(--accent)] transition-colors cursor-pointer block"
              >
                <p className="text-xs text-muted uppercase tracking-wide">
                  This Month — Net
                </p>
                <p
                  className={`text-2xl font-semibold mt-1 ${monthNet.isNegative() ? "text-[var(--error)]" : "text-[var(--success)]"}`}
                >
                  {formatCurrencyLocale(
                    monthNet,
                    currency,
                    "en-US",
                    fmtOpts,
                  )}
                </p>
                <p className="text-xs text-muted mt-1">
                  {monthNet.isNegative() ? "Deficit" : "Surplus"}
                </p>
              </Link>
            </div>
          );
        })()}
    </>
  );
}

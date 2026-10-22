"use client";

import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import { AccountLineageDrawer, type AccountLineageTarget } from "@/components/reports/AccountLineageDrawer";
import { OpeningBalanceWarningBanner } from "@/components/reports/ReportPageShell";
import { compareAmounts, formatCurrencyLocale, subtractAmounts, toDecimal } from "@/lib/audit/money";
import { formatPercentFromPercentValue, percentNumberFromParts } from "@/lib/audit/ratio/format";
import { formatDateInput, formatMonthLabel } from "@/lib/date";
import type { BalanceSheetResponse, IncomeStatementResponse, ReportLine } from "@/lib/types";

export type CockpitPeriodPreset = "1M" | "1Q" | "1Y" | "YTD" | "3Y" | "All";
export const COCKPIT_PERIOD_STORAGE_KEY = "finance_report.cockpit_period";
export const COCKPIT_PERIOD_PRESETS: CockpitPeriodPreset[] = ["1M", "1Q", "1Y", "YTD", "3Y", "All"];
const CURRENCY_OPTIONS = ["SGD", "USD", "CNY", "EUR", "GBP", "HKD", "JPY"];
const FMT_OPTS = { maximumFractionDigits: 0 } as const;
const CASH_RE = /cash|bank|checking|saving|multiplier|wallet/i;
const fmtMoney = (val: string | number | ReturnType<typeof toDecimal>, currency: string) =>
  formatCurrencyLocale(val, currency, "en-US", FMT_OPTS);

export function resolvePeriodRange(preset: CockpitPeriodPreset, referenceDate: Date = new Date()): { startDate: string; endDate: string } {
  const endDate = formatDateInput(referenceDate);
  const year = referenceDate.getFullYear();
  const month = referenceDate.getMonth();
  if (preset === "1M") return { startDate: formatDateInput(new Date(year, month, 1)), endDate };
  if (preset === "1Q") return { startDate: formatDateInput(new Date(year, month - 2, 1)), endDate };
  if (preset === "YTD") return { startDate: formatDateInput(new Date(year, 0, 1)), endDate };
  if (preset === "3Y") return { startDate: formatDateInput(new Date(year, month - 35, 1)), endDate };
  if (preset === "All") return { startDate: "2000-01-01", endDate };
  return { startDate: formatDateInput(new Date(year, month - 11, 1)), endDate };
}

export interface CockpitOnboardingStatus {
  accountCount: number; statementCount: number; approvedStatementCount: number; postedEntryCount: number;
}

interface ThreeStatementNavProps {
  balanceSheet?: BalanceSheetResponse | null; incomeStatement?: IncomeStatementResponse | null;
  periodPreset?: CockpitPeriodPreset; onPeriodPresetChange?: (preset: CockpitPeriodPreset) => void;
  includeRestricted?: boolean; onIncludeRestrictedChange?: (include: boolean) => void;
  onCurrencyChange?: (currency: string) => void; onboardingStatus?: CockpitOnboardingStatus | null;
}

type ActiveStatementTab = "balance" | "income" | "cash";

function ProportionalBar({ label, rightText, pct, barClass, textClass = "" }: {
  label: string; rightText?: string; pct: number; barClass: string; textClass?: string;
}) {
  return (
    <div>
      <div className={`flex justify-between font-medium ${textClass}`}>
        <span className="truncate">{label}</span>{rightText && <span>{rightText}</span>}
      </div>
      <div className="mt-0.5 h-2 rounded-full bg-[var(--background-muted)] overflow-hidden">
        <div className={`h-full rounded-full ${barClass}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function StatementCardLink({ href, testId, title, subtitle, summary, badge }: {
  href: string; testId: string; title: string; subtitle: string; summary: string | null; badge?: ReactNode;
}) {
  return (
    <Link href={href} data-testid={testId} className="card p-3 text-center sm:text-left transition-colors hover:border-[var(--accent)] hover:bg-[var(--background-muted)]">
      <span className="flex items-center justify-between text-sm font-medium"><span>{title}</span><span aria-hidden="true" className="text-xs text-[var(--accent)]">↗</span></span>
      <span className="mt-0.5 block text-xs text-muted">{subtitle}</span>
      {summary && <span className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs font-semibold text-[var(--foreground)]"><span>{summary}</span>{badge}</span>}
    </Link>
  );
}

export function ThreeStatementNav({
  balanceSheet = null, incomeStatement = null, periodPreset = "1Y", onPeriodPresetChange,
  includeRestricted = false, onIncludeRestrictedChange, onCurrencyChange, onboardingStatus = null,
}: ThreeStatementNavProps = {}) {
  const [internalPreset, setInternalPreset] = useState<CockpitPeriodPreset>(periodPreset);
  const [activeTab, setActiveTab] = useState<ActiveStatementTab>("balance");
  const [lineageTarget, setLineageTarget] = useState<AccountLineageTarget | null>(null);

  const effectivePreset = onPeriodPresetChange ? periodPreset : internalPreset;
  const currency = balanceSheet?.currency || incomeStatement?.currency || "SGD";

  const handlePresetClick = (preset: CockpitPeriodPreset) => {
    try {
      if (typeof window !== "undefined") window.sessionStorage.setItem(COCKPIT_PERIOD_STORAGE_KEY, preset);
    } catch { /* ignore storage errors */ }
    if (onPeriodPresetChange) onPeriodPresetChange(preset);
    else setInternalPreset(preset);
  };

  const netPositionText = useMemo(() => {
    if (!balanceSheet) return null;
    const net = subtractAmounts(balanceSheet.total_assets, balanceSheet.total_liabilities);
    return `Position ${fmtMoney(net, currency)} · Own ${fmtMoney(balanceSheet.total_assets, currency)} / Owe ${fmtMoney(balanceSheet.total_liabilities, currency)}`;
  }, [balanceSheet, currency]);

  const incomeSummary = useMemo(() => {
    if (!incomeStatement) return null;
    const latest = incomeStatement.trends?.length ? incomeStatement.trends[incomeStatement.trends.length - 1] : null;
    const hasTotals = !toDecimal(incomeStatement.total_income).isZero() || !toDecimal(incomeStatement.total_expenses).isZero();
    const totalIn = hasTotals ? toDecimal(incomeStatement.total_income) : latest ? toDecimal(latest.total_income) : toDecimal("0");
    const totalOut = hasTotals ? toDecimal(incomeStatement.total_expenses) : latest ? toDecimal(latest.total_expenses) : toDecimal("0");
    const net = hasTotals ? toDecimal(incomeStatement.net_income) : latest ? totalIn.minus(totalOut) : toDecimal("0");
    const rateNum = totalIn.greaterThan(0) ? (percentNumberFromParts(net.toString(), totalIn.toString(), { dp: 0, fallback: 0 }) ?? 0) : 0;
    const savingsRate = formatPercentFromPercentValue(String(rateNum), { dp: 0, fallback: "0%" });
    return {
      text: `Net ${fmtMoney(net, currency)} · Save rate ${savingsRate}`,
      statusLabel: hasTotals || Boolean(latest) ? (net.isNegative() ? "Deficit" : "Surplus") : null,
    };
  }, [incomeStatement, currency]);

  const cashSummaryText = useMemo(() => {
    if (!balanceSheet) return null;
    const cashAssets = balanceSheet.assets.filter((a) => CASH_RE.test(a.name));
    const liquidTotal = (cashAssets.length > 0 ? cashAssets : balanceSheet.assets).reduce((acc, r) => acc.plus(toDecimal(r.amount)), toDecimal("0"));
    return `Liquid cash ${fmtMoney(liquidTotal, currency)}`;
  }, [balanceSheet, currency]);

  const breakdownLines: ReportLine[] = useMemo(() => {
    if (activeTab === "balance" && balanceSheet) return [...balanceSheet.assets, ...balanceSheet.liabilities].slice(0, 6);
    if (activeTab === "income" && incomeStatement) return [...incomeStatement.income, ...incomeStatement.expenses].slice(0, 6);
    if (!balanceSheet) return [];
    const cashRows = balanceSheet.assets.filter((a) => CASH_RE.test(a.name));
    return (cashRows.length > 0 ? cashRows : balanceSheet.assets).slice(0, 6);
  }, [activeTab, balanceSheet, incomeStatement]);

  const openLineageForAccount = (line: ReportLine) => {
    const range = resolvePeriodRange(effectivePreset);
    setLineageTarget({
      accountId: line.account_id,
      accountName: line.name,
      asOfDate: balanceSheet?.as_of_date || incomeStatement?.end_date || range.endDate,
      startDate: activeTab === "balance" ? undefined : incomeStatement?.start_date || range.startDate,
      currency,
    });
  };

  const hasStatementData = Boolean(balanceSheet || incomeStatement);
  const isCoreFlowComplete =
    ((onboardingStatus?.approvedStatementCount ?? 0) > 0 && (onboardingStatus?.postedEntryCount ?? 0) > 0) ||
    ((onboardingStatus?.postedEntryCount ?? 0) > 0 && (onboardingStatus?.statementCount ?? 0) === 0);
  const showOnboarding = onboardingStatus !== null && !isCoreFlowComplete;
  const currencyChoices = Array.from(new Set([currency, ...CURRENCY_OPTIONS]));

  const renderVisualChart = () => {
    if (activeTab === "balance" && balanceSheet) {
      const totalAssets = toDecimal(balanceSheet.total_assets);
      const totalLiabs = toDecimal(balanceSheet.total_liabilities);
      const maxSide = Math.max(totalAssets.toNumber(), totalLiabs.toNumber(), 1);
      const assetPct = Math.min(100, Math.round((totalAssets.toNumber() / maxSide) * 100));
      const liabPct = Math.min(100, Math.round((totalLiabs.toNumber() / maxSide) * 100));
      const topAssets = [...balanceSheet.assets].filter((a) => compareAmounts(a.amount, "0") > 0).sort((a, b) => compareAmounts(b.amount, a.amount)).slice(0, 3);
      return (
        <div className="space-y-2 text-xs">
          <p className="font-medium text-muted uppercase tracking-wide text-[11px]">Assets vs Liabilities & Top Allocation</p>
          <div className="space-y-1.5">
            <ProportionalBar label="Total Assets" rightText={`${fmtMoney(totalAssets, currency)} (${assetPct}%)`} pct={assetPct} barClass="bg-[var(--success)]" textClass="text-[var(--success)]" />
            <ProportionalBar label="Total Liabilities" rightText={`${fmtMoney(totalLiabs, currency)} (${liabPct}%)`} pct={liabPct} barClass="bg-[var(--error)]" textClass="text-[var(--error)]" />
          </div>
          {topAssets.length > 0 && (
            <div className="pt-1.5 border-t border-[var(--border)] space-y-1">
              {topAssets.map((a) => {
                const share = totalAssets.greaterThan(0) ? Math.round(toDecimal(a.amount).dividedBy(totalAssets).times(100).toNumber()) : 0;
                return <div key={a.account_id} className="truncate text-[11px] text-muted">{`${a.name} (${share}% · ${fmtMoney(a.amount, currency)})`}</div>;
              })}
            </div>
          )}
        </div>
      );
    }
    if (activeTab === "income" && incomeStatement) {
      const trends = incomeStatement.trends?.slice(-4) ?? [];
      const rows = trends.length > 0 ? trends : [{ period_start: incomeStatement.start_date, total_income: incomeStatement.total_income, total_expenses: incomeStatement.total_expenses }];
      const maxTrend = Math.max(...rows.flatMap((t) => [toDecimal(t.total_income).toNumber(), toDecimal(t.total_expenses).toNumber()]), 1);
      return (
        <div className="space-y-1.5 text-xs">
          <p className="font-medium text-muted uppercase tracking-wide text-[11px]">Income vs Expenses Trend</p>
          {rows.map((t) => {
            const inc = toDecimal(t.total_income);
            const exp = toDecimal(t.total_expenses);
            return (
              <div key={t.period_start} className="space-y-0.5">
                <span className="block text-[11px] font-medium">{`${formatMonthLabel(t.period_start)} · Net ${fmtMoney(inc.minus(exp), currency)}`}</span>
                <div className="flex gap-1 h-1.5">
                  <div className="rounded-full bg-[var(--success)]" style={{ width: `${Math.min(100, Math.round((inc.toNumber() / maxTrend) * 100))}%` }} />
                  <div className="rounded-full bg-[var(--error)]" style={{ width: `${Math.min(100, Math.round((exp.toNumber() / maxTrend) * 100))}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      );
    }
    if (activeTab === "cash" && balanceSheet) {
      const totalAssets = toDecimal(balanceSheet.total_assets);
      const cashRows = balanceSheet.assets.filter((a) => CASH_RE.test(a.name));
      const rows = cashRows.length > 0 ? cashRows : balanceSheet.assets.slice(0, 3);
      return (
        <div className="space-y-1.5 text-xs">
          <p className="font-medium text-muted uppercase tracking-wide text-[11px]">Liquid Cash vs Total Assets</p>
          {rows.map((r) => {
            const amt = toDecimal(r.amount);
            const share = totalAssets.greaterThan(0) ? Math.min(100, Math.round(amt.dividedBy(totalAssets).times(100).toNumber())) : 0;
            return <ProportionalBar key={r.account_id} label={`${r.name} (${share}% · ${fmtMoney(amt, currency)})`} pct={share} barClass="bg-[var(--accent)]" textClass="text-[11px]" />;
          })}
        </div>
      );
    }
    return null;
  };

  return (
    <div className="space-y-3">
      {showOnboarding && (
        <section className="card p-3 border-[var(--accent)]/40" aria-label="Getting started">
          <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
            <h2 className="text-sm font-semibold">Build your first accurate financial view</h2>
            <div className="grid gap-2 sm:grid-cols-3">
              {[
                { label: "Upload a bank statement", href: "/upload", done: (onboardingStatus?.statementCount ?? 0) > 0 },
                { label: "Review and approve", href: "/upload", done: isCoreFlowComplete },
                { label: "Read your reports", href: "/reports", done: isCoreFlowComplete },
              ].map(({ label, href, done }) => (
                <Link key={label} href={href} className="flex items-center justify-between gap-2 rounded-md border border-[var(--border)] px-2.5 py-1.5 text-xs hover:border-[var(--accent)]">
                  <span className="font-medium">{label}</span>
                  <span className="text-muted">{done ? "Done" : "Next"}</span>
                </Link>
              ))}
            </div>
          </div>
        </section>
      )}
      <OpeningBalanceWarningBanner warnings={balanceSheet?.opening_balance_warnings} />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-muted">Unified Statement Cockpit ({effectivePreset})</span>
          {onCurrencyChange ? (
            <select aria-label="Reporting currency" value={currency} onChange={(e) => onCurrencyChange(e.target.value)} className="rounded border border-[var(--border)] bg-[var(--background-card)] px-2 py-0.5 text-[11px] font-medium text-muted">
              {currencyChoices.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          ) : (
            <span className="rounded bg-[var(--background-muted)] px-2 py-0.5 text-[11px] font-medium text-muted">{currency}</span>
          )}
          {onIncludeRestrictedChange && (
            <button type="button" aria-label="Include restricted holdings" aria-pressed={Boolean(includeRestricted)} onClick={() => onIncludeRestrictedChange(!includeRestricted)} className={`rounded border px-2 py-0.5 text-[11px] font-medium transition-colors ${includeRestricted ? "border-[var(--accent)] bg-[var(--accent-muted)] text-[var(--accent)]" : "border-[var(--border)] bg-[var(--background-card)] text-muted hover:text-[var(--foreground)]"}`}>
              <span className="sr-only">Include restricted holdings</span>
              {includeRestricted ? "Scope: + RSU" : "Scope: Liquid"}
            </button>
          )}
        </div>
        <div role="group" aria-label="Reporting period" className="inline-flex flex-wrap items-center gap-1 rounded-lg bg-[var(--background-muted)] p-1">
          {COCKPIT_PERIOD_PRESETS.map((preset) => (
            <button key={preset} type="button" aria-label={`Period ${preset}`} aria-pressed={effectivePreset === preset} onClick={() => handlePresetClick(preset)} className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${effectivePreset === preset ? "bg-[var(--background-card)] text-[var(--foreground)] shadow-sm" : "text-muted hover:text-[var(--foreground)]"}`}>
              {preset}
            </button>
          ))}
        </div>
      </div>
      <nav aria-label="Financial statements" className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <StatementCardLink href="/reports/balance-sheet" testId="cockpit-card-balance-sheet" title="Balance Sheet" subtitle="What you own and owe" summary={netPositionText} />
        <StatementCardLink href="/reports/income-statement" testId="cockpit-card-income-statement" title="Income" subtitle="Money in and out" summary={incomeSummary?.text ?? null} badge={incomeSummary?.statusLabel && <span className={`badge ${incomeSummary.statusLabel === "Deficit" ? "badge-error" : "badge-success"}`}>{incomeSummary.statusLabel}</span>} />
        <StatementCardLink href="/reports/cash-flow" testId="cockpit-card-cash-flow" title="Cash Flow" subtitle="Where cash moved" summary={cashSummaryText} />
      </nav>
      {hasStatementData && (
        <div className="card p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div role="tablist" aria-label="Statement breakdown switcher" className="inline-flex rounded-md bg-[var(--background-muted)] p-0.5">
              {([["balance", "Balance Breakdown"], ["income", "Income Breakdown"], ["cash", "Cash Breakdown"]] as const).map(([id, label]) => (
                <button key={id} type="button" role="tab" aria-selected={activeTab === id} onClick={() => setActiveTab(id)} className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${activeTab === id ? "bg-[var(--background-card)] text-[var(--foreground)] shadow-sm" : "text-muted hover:text-[var(--foreground)]"}`}>
                  {label}
                </button>
              ))}
            </div>
            <span className="text-[11px] text-muted">{`${currency} · Click any row (›) to inspect source lineage`}</span>
          </div>
          <div className="mt-2.5 grid gap-3 lg:grid-cols-12">
            <div data-testid="cockpit-visual-chart" role="img" aria-label={`Cockpit ${activeTab} visual chart`} className="lg:col-span-6 rounded-md border border-[var(--border)] bg-[var(--background-muted)]/30 p-3">
              {renderVisualChart()}
            </div>
            {breakdownLines.length > 0 && (
              <div className="lg:col-span-6 grid grid-cols-1 gap-1.5 sm:grid-cols-2 content-start">
                {breakdownLines.map((line) => (
                  <button key={line.account_id} type="button" aria-label={`Drill down ${line.name}`} onClick={() => openLineageForAccount(line)} className="flex items-center justify-between gap-2 rounded-md border border-[var(--border)] bg-[var(--background-muted)]/50 px-3 py-1.5 text-left text-xs font-medium hover:border-[var(--accent)] transition-colors">
                    {`${line.name} · ${fmtMoney(line.amount, currency)} ›`}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
      <AccountLineageDrawer target={lineageTarget} onClose={() => setLineageTarget(null)} />
    </div>
  );
}

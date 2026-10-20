"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import {
    AccountLineageDrawer,
    type AccountLineageTarget,
} from "@/components/reports/AccountLineageDrawer";
import {
    compareAmounts,
    formatCurrencyLocale,
    subtractAmounts,
    toDecimal,
} from "@/lib/audit/money";
import { formatDateInput, formatMonthLabel } from "@/lib/date";
import type {
    BalanceSheetResponse,
    IncomeStatementResponse,
    ReportLine,
} from "@/lib/types";

export type CockpitPeriodPreset = "1M" | "1Q" | "1Y" | "YTD" | "3Y" | "All";

export const COCKPIT_PERIOD_STORAGE_KEY = "finance_report.cockpit_period";

export const COCKPIT_PERIOD_PRESETS: CockpitPeriodPreset[] = [
    "1M",
    "1Q",
    "1Y",
    "YTD",
    "3Y",
    "All",
];

export function resolvePeriodRange(
    preset: CockpitPeriodPreset,
    referenceDate: Date = new Date(),
): { startDate: string; endDate: string } {
    const endDate = formatDateInput(referenceDate);
    const year = referenceDate.getFullYear();
    const month = referenceDate.getMonth();

    switch (preset) {
        case "1M":
            return {
                startDate: formatDateInput(new Date(year, month, 1)),
                endDate,
            };
        case "1Q":
            return {
                startDate: formatDateInput(new Date(year, month - 2, 1)),
                endDate,
            };
        case "YTD":
            return {
                startDate: formatDateInput(new Date(year, 0, 1)),
                endDate,
            };
        case "3Y":
            return {
                startDate: formatDateInput(new Date(year, month - 35, 1)),
                endDate,
            };
        case "All":
            return {
                startDate: "2000-01-01",
                endDate,
            };
        case "1Y":
        default:
            return {
                startDate: formatDateInput(new Date(year, month - 11, 1)),
                endDate,
            };
    }
}

interface ThreeStatementNavProps {
    balanceSheet?: BalanceSheetResponse | null;
    incomeStatement?: IncomeStatementResponse | null;
    periodPreset?: CockpitPeriodPreset;
    onPeriodPresetChange?: (preset: CockpitPeriodPreset) => void;
    includeRestricted?: boolean;
    onIncludeRestrictedChange?: (include: boolean) => void;
}

type ActiveStatementTab = "balance" | "income" | "cash";
const FMT_OPTS = { maximumFractionDigits: 0 } as const;

export function ThreeStatementNav({
    balanceSheet = null,
    incomeStatement = null,
    periodPreset = "1Y",
    onPeriodPresetChange,
    includeRestricted = false,
    onIncludeRestrictedChange,
}: ThreeStatementNavProps = {}) {
    const [internalPreset, setInternalPreset] =
        useState<CockpitPeriodPreset>(periodPreset);
    const [activeTab, setActiveTab] = useState<ActiveStatementTab>("balance");
    const [lineageTarget, setLineageTarget] =
        useState<AccountLineageTarget | null>(null);

    const effectivePreset = onPeriodPresetChange
        ? periodPreset
        : internalPreset;

    const handlePresetClick = (preset: CockpitPeriodPreset) => {
        try {
            window.sessionStorage.setItem(COCKPIT_PERIOD_STORAGE_KEY, preset);
        } catch {
            // Storage may be restricted in privacy modes.
        }
        if (onPeriodPresetChange) {
            onPeriodPresetChange(preset);
        } else {
            setInternalPreset(preset);
        }
    };

    const currency =
        balanceSheet?.currency || incomeStatement?.currency || "SGD";

    const netPositionText = useMemo(() => {
        if (!balanceSheet) return null;
        const net = subtractAmounts(
            balanceSheet.total_assets,
            balanceSheet.total_liabilities,
        );
        const assets = formatCurrencyLocale(
            balanceSheet.total_assets,
            currency,
            "en-US",
            FMT_OPTS,
        );
        const debt = formatCurrencyLocale(
            balanceSheet.total_liabilities,
            currency,
            "en-US",
            FMT_OPTS,
        );
        const netFormatted = formatCurrencyLocale(
            net,
            currency,
            "en-US",
            FMT_OPTS,
        );
        return `Position ${netFormatted} · Own ${assets} / Owe ${debt}`;
    }, [balanceSheet, currency]);

    const incomeSummaryText = useMemo(() => {
        if (!incomeStatement) return null;
        const totalIn = toDecimal(incomeStatement.total_income);
        const net = toDecimal(incomeStatement.net_income);
        const savingsRate = totalIn.greaterThan(0)
            ? `${Math.round(net.dividedBy(totalIn).times(100).toNumber())}%`
            : "0%";
        const netFmt = formatCurrencyLocale(net, currency, "en-US", FMT_OPTS);
        return `Net ${netFmt} · Save rate ${savingsRate}`;
    }, [incomeStatement, currency]);

    const cashSummaryText = useMemo(() => {
        if (!balanceSheet) return null;
        const cashAssets = balanceSheet.assets.filter((a) =>
            /cash|bank|checking|saving|multiplier|wallet/i.test(a.name),
        );
        const liquidTotal = (
            cashAssets.length > 0 ? cashAssets : balanceSheet.assets
        ).reduce(
            (acc, row) => acc.plus(toDecimal(row.amount)),
            toDecimal("0"),
        );
        const liquidFmt = formatCurrencyLocale(
            liquidTotal,
            currency,
            "en-US",
            FMT_OPTS,
        );
        return `Liquid cash ${liquidFmt}`;
    }, [balanceSheet, currency]);

    const breakdownLines: ReportLine[] = useMemo(() => {
        if (activeTab === "balance" && balanceSheet) {
            return [
                ...balanceSheet.assets,
                ...balanceSheet.liabilities,
            ].slice(0, 6);
        }
        if (activeTab === "income" && incomeStatement) {
            return [
                ...incomeStatement.income,
                ...incomeStatement.expenses,
            ].slice(0, 6);
        }
        if (!balanceSheet) return [];
        const cashRows = balanceSheet.assets.filter((a) =>
            /cash|bank|checking|saving|multiplier|wallet/i.test(a.name),
        );
        return (cashRows.length > 0 ? cashRows : balanceSheet.assets).slice(
            0,
            6,
        );
    }, [activeTab, balanceSheet, incomeStatement]);

    const openLineageForAccount = (line: ReportLine) => {
        const range = resolvePeriodRange(effectivePreset);
        const asOfDate =
            balanceSheet?.as_of_date ||
            incomeStatement?.end_date ||
            range.endDate;
        const startDate =
            activeTab === "balance"
                ? undefined
                : incomeStatement?.start_date || range.startDate;
        setLineageTarget({
            accountId: line.account_id,
            accountName: line.name,
            asOfDate,
            startDate,
            currency,
        });
    };

    const hasStatementData = Boolean(balanceSheet || incomeStatement);

    return (
        <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-medium uppercase tracking-wide text-muted">
                        Unified Statement Cockpit ({effectivePreset})
                    </span>
                    <span className="rounded bg-[var(--background-muted)] px-2 py-0.5 text-[11px] font-medium text-muted">
                        {currency}
                    </span>
                    {onIncludeRestrictedChange && (
                        <button
                            type="button"
                            aria-label="Toggle restricted holdings scope"
                            aria-pressed={Boolean(includeRestricted)}
                            onClick={() =>
                                onIncludeRestrictedChange(!includeRestricted)
                            }
                            className={`rounded border px-2 py-0.5 text-[11px] font-medium transition-colors ${
                                includeRestricted
                                    ? "border-[var(--accent)] bg-[var(--accent-muted)] text-[var(--accent)]"
                                    : "border-[var(--border)] bg-[var(--background-card)] text-muted hover:text-[var(--foreground)]"
                            }`}
                        >
                            {includeRestricted ? "Scope: + RSU" : "Scope: Liquid"}
                        </button>
                    )}
                </div>
                <div
                    role="group"
                    aria-label="Reporting period"
                    className="inline-flex flex-wrap items-center gap-1 rounded-lg bg-[var(--background-muted)] p-1"
                >
                    {COCKPIT_PERIOD_PRESETS.map((preset) => {
                        const active = effectivePreset === preset;
                        return (
                            <button
                                key={preset}
                                type="button"
                                aria-label={`Period ${preset}`}
                                aria-pressed={active}
                                onClick={() => handlePresetClick(preset)}
                                className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                                    active
                                        ? "bg-[var(--background-card)] text-[var(--foreground)] shadow-sm"
                                        : "text-muted hover:text-[var(--foreground)]"
                                }`}
                            >
                                {preset}
                            </button>
                        );
                    })}
                </div>
            </div>

            <nav
                aria-label="Financial statements"
                className="grid grid-cols-1 gap-2 sm:grid-cols-3"
            >
                <Link
                    href="/reports/balance-sheet"
                    data-testid="cockpit-card-balance-sheet"
                    className="card p-3 text-center sm:text-left transition-colors hover:border-[var(--accent)] hover:bg-[var(--background-muted)]"
                >
                    <span className="flex items-center justify-between text-sm font-medium">
                        <span>Balance Sheet</span>
                        <span aria-hidden="true" className="text-xs text-[var(--accent)]">↗</span>
                    </span>
                    <span className="mt-0.5 block text-xs text-muted">
                        What you own and owe
                    </span>
                    {netPositionText && (
                        <span className="mt-1.5 block text-xs font-semibold text-[var(--foreground)]">
                            {netPositionText}
                        </span>
                    )}
                </Link>

                <Link
                    href="/reports/income-statement"
                    data-testid="cockpit-card-income-statement"
                    className="card p-3 text-center sm:text-left transition-colors hover:border-[var(--accent)] hover:bg-[var(--background-muted)]"
                >
                    <span className="flex items-center justify-between text-sm font-medium">
                        <span>Income</span>
                        <span aria-hidden="true" className="text-xs text-[var(--accent)]">↗</span>
                    </span>
                    <span className="mt-0.5 block text-xs text-muted">
                        Money in and out
                    </span>
                    {incomeSummaryText && (
                        <span className="mt-1.5 block text-xs font-semibold text-[var(--foreground)]">
                            {incomeSummaryText}
                        </span>
                    )}
                </Link>

                <Link
                    href="/reports/cash-flow"
                    data-testid="cockpit-card-cash-flow"
                    className="card p-3 text-center sm:text-left transition-colors hover:border-[var(--accent)] hover:bg-[var(--background-muted)]"
                >
                    <span className="flex items-center justify-between text-sm font-medium">
                        <span>Cash Flow</span>
                        <span aria-hidden="true" className="text-xs text-[var(--accent)]">↗</span>
                    </span>
                    <span className="mt-0.5 block text-xs text-muted">
                        Where cash moved
                    </span>
                    {cashSummaryText && (
                        <span className="mt-1.5 block text-xs font-semibold text-[var(--foreground)]">
                            {cashSummaryText}
                        </span>
                    )}
                </Link>
            </nav>

            {hasStatementData && (
                <div className="card p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <div
                            role="tablist"
                            aria-label="Statement breakdown switcher"
                            className="inline-flex rounded-md bg-[var(--background-muted)] p-0.5"
                        >
                            {(
                                [
                                    {
                                        id: "balance",
                                        label: "Balance Breakdown",
                                    },
                                    { id: "income", label: "Income Breakdown" },
                                    { id: "cash", label: "Cash Breakdown" },
                                ] as const
                            ).map((tab) => {
                                const selected = activeTab === tab.id;
                                return (
                                    <button
                                        key={tab.id}
                                        type="button"
                                        role="tab"
                                        aria-selected={selected}
                                        onClick={() => setActiveTab(tab.id)}
                                        className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                                            selected
                                                ? "bg-[var(--background-card)] text-[var(--foreground)] shadow-sm"
                                                : "text-muted hover:text-[var(--foreground)]"
                                        }`}
                                    >
                                        {tab.label}
                                    </button>
                                );
                            })}
                        </div>
                        <span className="text-[11px] text-muted">
                            {`${currency} · Click any row (›) to inspect source lineage`}
                        </span>
                    </div>

                    <div className="mt-2.5 grid gap-3 lg:grid-cols-12">
                        <div
                            data-testid="cockpit-visual-chart"
                            role="img"
                            aria-label={`Cockpit ${activeTab} visual chart`}
                            className="lg:col-span-6 rounded-md border border-[var(--border)] bg-[var(--background-muted)]/30 p-3"
                        >
                            {activeTab === "balance" && balanceSheet && (() => {
                                const totalAssets = toDecimal(
                                    balanceSheet.total_assets,
                                );
                                const totalLiabs = toDecimal(
                                    balanceSheet.total_liabilities,
                                );
                                const maxSide = Math.max(
                                    totalAssets.toNumber(),
                                    totalLiabs.toNumber(),
                                    1,
                                );
                                const assetPct = Math.min(
                                    100,
                                    Math.round(
                                        (totalAssets.toNumber() / maxSide) *
                                            100,
                                    ),
                                );
                                const liabPct = Math.min(
                                    100,
                                    Math.round(
                                        (totalLiabs.toNumber() / maxSide) *
                                            100,
                                    ),
                                );
                                const topAssets = [...balanceSheet.assets]
                                    .filter(
                                        (a) =>
                                            compareAmounts(a.amount, "0") > 0,
                                    )
                                    .sort((a, b) =>
                                        compareAmounts(b.amount, a.amount),
                                    )
                                    .slice(0, 3);
                                return (
                                    <div className="space-y-2 text-xs">
                                        <p className="font-medium text-muted uppercase tracking-wide text-[11px]">
                                            Assets vs Liabilities & Top Allocation
                                        </p>
                                        <div className="space-y-1.5">
                                            <div>
                                                <div className="flex justify-between font-medium text-[var(--success)]">
                                                    <span>{`Assets: ${formatCurrencyLocale(totalAssets, currency, "en-US", FMT_OPTS)} (${assetPct}%)`}</span>
                                                </div>
                                                <div className="mt-0.5 h-2 rounded-full bg-[var(--background-muted)] overflow-hidden">
                                                    <div
                                                        className="h-full rounded-full bg-[var(--success)]"
                                                        style={{
                                                            width: `${assetPct}%`,
                                                        }}
                                                    />
                                                </div>
                                            </div>
                                            <div>
                                                <div className="flex justify-between font-medium text-[var(--error)]">
                                                    <span>{`Liabilities: ${formatCurrencyLocale(totalLiabs, currency, "en-US", FMT_OPTS)} (${liabPct}%)`}</span>
                                                </div>
                                                <div className="mt-0.5 h-2 rounded-full bg-[var(--background-muted)] overflow-hidden">
                                                    <div
                                                        className="h-full rounded-full bg-[var(--error)]"
                                                        style={{
                                                            width: `${liabPct}%`,
                                                        }}
                                                    />
                                                </div>
                                            </div>
                                        </div>
                                        {topAssets.length > 0 && (
                                            <div className="pt-1.5 border-t border-[var(--border)] space-y-1">
                                                {topAssets.map((asset) => {
                                                    const share =
                                                        totalAssets.greaterThan(
                                                            0,
                                                        )
                                                            ? Math.round(
                                                                  toDecimal(
                                                                      asset.amount,
                                                                  )
                                                                      .dividedBy(
                                                                          totalAssets,
                                                                      )
                                                                      .times(
                                                                          100,
                                                                      )
                                                                      .toNumber(),
                                                              )
                                                            : 0;
                                                    return (
                                                        <div
                                                            key={
                                                                asset.account_id
                                                            }
                                                            className="flex items-center justify-between gap-2 text-[11px] text-muted"
                                                        >
                                                            <span className="truncate">
                                                                {`${asset.name} (${share}% · ${formatCurrencyLocale(asset.amount, currency, "en-US", FMT_OPTS)})`}
                                                            </span>
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        )}
                                    </div>
                                );
                            })()}
                            {activeTab === "income" && incomeStatement && (() => {
                                const trends =
                                    incomeStatement.trends?.slice(-4) ?? [];
                                const effectiveTrends =
                                    trends.length > 0
                                        ? trends
                                        : [
                                              {
                                                  period_start:
                                                      incomeStatement.start_date,
                                                  total_income:
                                                      incomeStatement.total_income,
                                                  total_expenses:
                                                      incomeStatement.total_expenses,
                                              },
                                          ];
                                const maxTrend = Math.max(
                                    ...effectiveTrends.flatMap((t) => [
                                        toDecimal(t.total_income).toNumber(),
                                        toDecimal(t.total_expenses).toNumber(),
                                    ]),
                                    1,
                                );
                                return (
                                    <div className="space-y-1.5 text-xs">
                                        <p className="font-medium text-muted uppercase tracking-wide text-[11px]">
                                            Income vs Expenses Trend
                                        </p>
                                        {effectiveTrends.map((t) => {
                                            const inc = toDecimal(
                                                t.total_income,
                                            );
                                            const exp = toDecimal(
                                                t.total_expenses,
                                            );
                                            const net = inc.minus(exp);
                                            const incPct = Math.min(
                                                100,
                                                Math.round(
                                                    (inc.toNumber() /
                                                        maxTrend) *
                                                        100,
                                                ),
                                            );
                                            const expPct = Math.min(
                                                100,
                                                Math.round(
                                                    (exp.toNumber() /
                                                        maxTrend) *
                                                        100,
                                                ),
                                            );
                                            return (
                                                <div
                                                    key={t.period_start}
                                                    className="space-y-0.5"
                                                >
                                                    <div className="flex justify-between text-[11px]">
                                                        <span className="font-medium">
                                                            {`${formatMonthLabel(t.period_start)} · Net ${formatCurrencyLocale(net, currency, "en-US", FMT_OPTS)}`}
                                                        </span>
                                                    </div>
                                                    <div className="flex gap-1 h-1.5">
                                                        <div
                                                            className="rounded-full bg-[var(--success)]"
                                                            style={{
                                                                width: `${incPct}%`,
                                                            }}
                                                        />
                                                        <div
                                                            className="rounded-full bg-[var(--error)]"
                                                            style={{
                                                                width: `${expPct}%`,
                                                            }}
                                                        />
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                );
                            })()}
                            {activeTab === "cash" && balanceSheet && (() => {
                                const totalAssets = toDecimal(
                                    balanceSheet.total_assets,
                                );
                                const cashRows = balanceSheet.assets.filter(
                                    (a) =>
                                        /cash|bank|checking|saving|multiplier|wallet/i.test(
                                            a.name,
                                        ),
                                );
                                const rows =
                                    cashRows.length > 0
                                        ? cashRows
                                        : balanceSheet.assets.slice(0, 3);
                                return (
                                    <div className="space-y-1.5 text-xs">
                                        <p className="font-medium text-muted uppercase tracking-wide text-[11px]">
                                            Liquid Cash vs Total Assets
                                        </p>
                                        {rows.map((row) => {
                                            const amt = toDecimal(row.amount);
                                            const share =
                                                totalAssets.greaterThan(0)
                                                    ? Math.min(
                                                          100,
                                                          Math.round(
                                                              amt
                                                                  .dividedBy(
                                                                      totalAssets,
                                                                  )
                                                                  .times(100)
                                                                  .toNumber(),
                                                          ),
                                                      )
                                                    : 0;
                                            return (
                                                <div
                                                    key={row.account_id}
                                                    className="space-y-0.5"
                                                >
                                                    <div className="flex justify-between text-[11px]">
                                                        <span className="truncate font-medium">
                                                            {`${row.name} (${share}% · ${formatCurrencyLocale(amt, currency, "en-US", FMT_OPTS)})`}
                                                        </span>
                                                    </div>
                                                    <div className="h-1.5 rounded-full bg-[var(--background-muted)] overflow-hidden">
                                                        <div
                                                            className="h-full rounded-full bg-[var(--accent)]"
                                                            style={{
                                                                width: `${share}%`,
                                                            }}
                                                        />
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                );
                            })()}
                        </div>

                        {breakdownLines.length > 0 && (
                            <div className="lg:col-span-6 grid grid-cols-1 gap-1.5 sm:grid-cols-2 content-start">
                                {breakdownLines.map((line) => {
                                    const amt = formatCurrencyLocale(
                                        line.amount,
                                        currency,
                                        "en-US",
                                        FMT_OPTS,
                                    );
                                    return (
                                        <button
                                            key={line.account_id}
                                            type="button"
                                            aria-label={`Drill down ${line.name}`}
                                            onClick={() =>
                                                openLineageForAccount(line)
                                            }
                                            className="flex items-center justify-between gap-2 rounded-md border border-[var(--border)] bg-[var(--background-muted)]/50 px-3 py-1.5 text-left text-xs font-medium hover:border-[var(--accent)] transition-colors"
                                        >
                                            {`${line.name} · ${amt} ›`}
                                        </button>
                                    );
                                })}
                            </div>
                        )}
                    </div>
                </div>
            )}

            <AccountLineageDrawer
                target={lineageTarget}
                onClose={() => setLineageTarget(null)}
            />
        </div>
    );
}

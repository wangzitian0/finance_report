"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import {
    AccountLineageDrawer,
    type AccountLineageTarget,
} from "@/components/reports/AccountLineageDrawer";
import {
    formatCurrencyLocale,
    subtractAmounts,
    toDecimal,
} from "@/lib/audit/money";
import { formatDateInput } from "@/lib/date";
import type {
    BalanceSheetResponse,
    IncomeStatementResponse,
    ReportLine,
} from "@/lib/types";

export type CockpitPeriodPreset = "1M" | "1Q" | "1Y" | "YTD" | "3Y" | "All";

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
}

type ActiveStatementTab = "balance" | "income" | "cash";
const FMT_OPTS = { maximumFractionDigits: 0 } as const;

export function ThreeStatementNav({
    balanceSheet = null,
    incomeStatement = null,
    periodPreset = "1Y",
    onPeriodPresetChange,
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
        if (onPeriodPresetChange) {
            onPeriodPresetChange(preset);
        } else {
            setInternalPreset(preset);
        }
    };

    const currency =
        balanceSheet?.currency ?? incomeStatement?.currency ?? "SGD";

    const netPositionText = useMemo(() => {
        if (!balanceSheet) return null;
        const net = subtractAmounts(
            balanceSheet.total_assets ?? "0",
            balanceSheet.total_liabilities ?? "0",
        );
        const assets = formatCurrencyLocale(
            balanceSheet.total_assets ?? "0",
            currency,
            "en-US",
            FMT_OPTS,
        );
        const debt = formatCurrencyLocale(
            balanceSheet.total_liabilities ?? "0",
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
        const totalIn = toDecimal(incomeStatement.total_income ?? "0");
        const totalOut = toDecimal(incomeStatement.total_expenses ?? "0");
        const net = toDecimal(
            incomeStatement.net_income ?? totalIn.minus(totalOut).toString(),
        );
        const savingsRate = totalIn.greaterThan(0)
            ? `${Math.round(net.dividedBy(totalIn).times(100).toNumber())}%`
            : "0%";
        const netFmt = formatCurrencyLocale(net, currency, "en-US", FMT_OPTS);
        return `Net ${netFmt} · Save rate ${savingsRate}`;
    }, [incomeStatement, currency]);

    const cashSummaryText = useMemo(() => {
        if (!balanceSheet && !incomeStatement) return null;
        const cashAssets = (balanceSheet?.assets ?? []).filter((a) =>
            /cash|bank|checking|saving|multiplier|wallet/i.test(a.name),
        );
        const liquidTotal = (
            cashAssets.length > 0 ? cashAssets : (balanceSheet?.assets ?? [])
        ).reduce(
            (acc, row) => acc.plus(toDecimal(row.amount ?? "0")),
            toDecimal("0"),
        );
        const liquidFmt = formatCurrencyLocale(
            liquidTotal,
            currency,
            "en-US",
            FMT_OPTS,
        );
        return `Liquid cash ${liquidFmt}`;
    }, [balanceSheet, incomeStatement, currency]);

    const breakdownLines: ReportLine[] = useMemo(() => {
        if (activeTab === "balance") {
            return [
                ...(balanceSheet?.assets ?? []),
                ...(balanceSheet?.liabilities ?? []),
            ].slice(0, 6);
        }
        if (activeTab === "income") {
            return [
                ...(incomeStatement?.income ?? []),
                ...(incomeStatement?.expenses ?? []),
            ].slice(0, 6);
        }
        const cashRows = (balanceSheet?.assets ?? []).filter((a) =>
            /cash|bank|checking|saving|multiplier|wallet/i.test(a.name),
        );
        return (cashRows.length > 0 ? cashRows : (balanceSheet?.assets ?? [])).slice(
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
                <span className="text-xs font-medium uppercase tracking-wide text-muted">
                    Unified Statement Cockpit ({effectivePreset})
                </span>
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
                    className="card p-3 text-center sm:text-left transition-colors hover:bg-[var(--background-muted)]"
                >
                    <span className="block text-sm font-medium">
                        Balance Sheet
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
                    className="card p-3 text-center sm:text-left transition-colors hover:bg-[var(--background-muted)]"
                >
                    <span className="block text-sm font-medium">Income</span>
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
                    className="card p-3 text-center sm:text-left transition-colors hover:bg-[var(--background-muted)]"
                >
                    <span className="block text-sm font-medium">Cash Flow</span>
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
                            Click any line to inspect journal lineage
                        </span>
                    </div>

                    {breakdownLines.length > 0 && (
                        <div className="mt-2.5 flex flex-wrap gap-2">
                            {breakdownLines.map((line) => {
                                const amt = formatCurrencyLocale(
                                    line.amount ?? "0",
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
                                        className="rounded-md border border-[var(--border)] bg-[var(--background-muted)]/50 px-2.5 py-1 text-xs font-medium hover:border-[var(--accent)] transition-colors"
                                    >
                                        {`${line.name} · ${amt}`}
                                    </button>
                                );
                            })}
                        </div>
                    )}
                </div>
            )}

            <AccountLineageDrawer
                target={lineageTarget}
                onClose={() => setLineageTarget(null)}
            />
        </div>
    );
}

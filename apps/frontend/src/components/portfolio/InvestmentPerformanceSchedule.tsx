"use client";

import { FileText, Link2 } from "lucide-react";

import { compareAmounts, formatCurrencyLocale } from "@/lib/audit/money";
import { computeMarketValuePerformance } from "@/lib/portfolioPerformance";
import { formatSignedPercentFromPercentValue } from "@/lib/audit/ratio/format";
import { humanizeIdentifier } from "@/lib/statusLabels";
import type { InvestmentPerformanceReportSchedule } from "@/lib/types";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const UUID_PREFIX_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-/i;

export function formatPerformanceSourceLink(link: string): string {
  const trimmed = link.trim();
  if (!trimmed) return "Source record";

  if (trimmed.startsWith("price_source:")) {
    const parts = trimmed.split(":");
    const kind = parts[1] ?? "";
    const ticker = parts[2] ?? "Holding";
    const lastPart = parts[parts.length - 1] ?? "";
    const hasDate = /^\d{4}-\d{2}-\d{2}$/.test(lastPart);
    const kindLabel =
      kind === "override" ||
      kind === "manual" ||
      kind === "market_data_override"
        ? "Manual price"
        : kind === "atomic_position" || kind === "position"
          ? "Position snapshot"
          : "Market price";
    return hasDate
      ? `${kindLabel} · ${ticker} (${lastPart})`
      : `${kindLabel} · ${ticker}`;
  }

  if (trimmed.startsWith("report_section:")) {
    const section = trimmed.slice("report_section:".length);
    return `Report section · ${humanizeIdentifier(section)}`;
  }

  const colonIdx = trimmed.indexOf(":");
  if (colonIdx > 0) {
    const docType = trimmed.slice(0, colonIdx);
    const target = trimmed.slice(colonIdx + 1);
    if (UUID_PATTERN.test(target) || UUID_PREFIX_PATTERN.test(target)) {
      return `${humanizeIdentifier(docType)} record`;
    }
  }

  return trimmed.replace(
    /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi,
    "record",
  );
}

function formatMarketDataProvider(provider: string | null | undefined): string {
  if (!provider) return "N/A";
  return provider
    .split(",")
    .map((part) => {
      const token = part.trim();
      if (!token) return "";
      return token.includes("_") ? humanizeIdentifier(token) : token;
    })
    .filter(Boolean)
    .join(", ");
}

function formatManualOverrideBasis(basis: string): string {
  const match = /^([^:]+):(\d{4}-\d{2}-\d{2})$/.exec(basis.trim());
  if (match) {
    return `${match[1]} (${match[2]})`;
  }
  return basis;
}

function metricClass(value: string | null): string {
  if (value === null) return "text-muted";
  try {
    const comparison = compareAmounts(value, "0");
    if (comparison === 0) return "";
    return comparison > 0 ? "text-[var(--success)]" : "text-[var(--error)]";
  } catch {
    return "";
  }
}

interface InvestmentPerformanceScheduleProps {
  schedule?: InvestmentPerformanceReportSchedule;
  isLoading?: boolean;
  error?: unknown;
}

export function InvestmentPerformanceSchedule({
  schedule,
  isLoading = false,
  error = null,
}: InvestmentPerformanceScheduleProps) {
  if (isLoading) {
    return (
      <div className="card p-5 mb-6" aria-busy="true">
        <p className="text-xs text-muted uppercase">
          Investment Performance Report Schedule
        </p>
        <div className="mt-4 h-5 w-5 rounded-full border-2 border-current border-t-transparent text-muted animate-spin" />
      </div>
    );
  }

  if (error || !schedule) {
    return (
      <div className="card p-5 mb-6">
        <p className="text-xs text-muted uppercase">
          Investment Performance Report Schedule
        </p>
        <p className="mt-3 text-sm text-muted">
          Unable to load investment performance schedule
        </p>
      </div>
    );
  }

  const analyticalMeasures = [
    { label: "XIRR", value: schedule.xirr },
    { label: "TWR", value: schedule.time_weighted_return },
    { label: "MWR", value: schedule.money_weighted_return },
    { label: "Dividend Yield", value: schedule.dividend_yield },
  ];
  const performance = computeMarketValuePerformance(schedule);
  const staleHoldings = schedule.data_freshness.stale_holdings ?? [];

  return (
    <section
      className="card p-5 mb-6"
      aria-labelledby="investment-performance-schedule-title"
    >
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <FileText
              className="h-4 w-4 text-[var(--accent)]"
              aria-hidden="true"
            />
            <h2
              id="investment-performance-schedule-title"
              className="text-base font-semibold"
            >
              Investment Performance Report Schedule
            </h2>
          </div>
          <p className="mt-1 text-xs text-muted">
            Report section{" "}
            <span className="font-medium text-[var(--foreground)]">
              {humanizeIdentifier(
                (
                  schedule as InvestmentPerformanceReportSchedule & {
                    report_section?: string;
                  }
                ).report_section ?? "investment_performance",
              )}
            </span>
            <span className="hidden" aria-hidden="true">
              investment_performance
            </span>
          </p>
        </div>
        <div className="text-xs text-muted md:text-right">
          <p>
            {schedule.period_start} to {schedule.period_end}
          </p>
          <p>
            As of {schedule.as_of_date} - {schedule.currency}
          </p>
        </div>
      </div>

      <p className="mt-5 text-xs text-muted uppercase">
        Market-value performance
      </p>
      <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded border border-[var(--border)] p-3">
          <p className="text-xs text-muted uppercase">Unrealized Gain/Loss</p>
          <p
            className={`mt-1 text-lg font-semibold ${metricClass(performance.unrealizedPnl)}`}
          >
            {formatCurrencyLocale(performance.unrealizedPnl, schedule.currency)}
          </p>
          <p className="mt-1 text-xs text-muted">
            vs cost{" "}
            {formatCurrencyLocale(
              performance.totalCostBasis,
              schedule.currency,
            )}
          </p>
        </div>
        <div className="rounded border border-[var(--border)] p-3">
          <p className="text-xs text-muted uppercase">Return on Cost</p>
          <p
            className={`mt-1 text-lg font-semibold ${metricClass(performance.returnOnCostPercent)}`}
          >
            {formatSignedPercentFromPercentValue(
              performance.returnOnCostPercent,
            )}
          </p>
          <p className="mt-1 text-xs text-muted">as of {schedule.as_of_date}</p>
        </div>
        <div className="rounded border border-[var(--border)] p-3">
          <p className="text-xs text-muted uppercase">Realized P&L</p>
          <p className="mt-1 font-semibold">
            {formatCurrencyLocale(schedule.realized_pnl, schedule.currency)}
          </p>
        </div>
        <div className="rounded border border-[var(--border)] p-3">
          <p className="text-xs text-muted uppercase">Dividend Income</p>
          <p className="mt-1 font-semibold">
            {formatCurrencyLocale(schedule.dividend_income, schedule.currency)}
          </p>
        </div>
      </div>

      <p className="mt-4 text-xs text-muted uppercase">
        Analytical return measures (reporting only)
      </p>
      <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {analyticalMeasures.map((metric) => (
          <div
            key={metric.label}
            className="rounded border border-[var(--border)] p-3"
          >
            <p className="text-xs text-muted uppercase">{metric.label}</p>
            <p
              className={`mt-1 text-lg font-semibold ${metricClass(metric.value)}`}
            >
              {formatSignedPercentFromPercentValue(metric.value)}
            </p>
          </div>
        ))}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div>
          <p className="text-xs text-muted uppercase">Data Freshness</p>
          <div className="mt-2 text-sm">
            <p>
              Latest price date:{" "}
              {schedule.data_freshness.latest_price_date ?? "N/A"}
            </p>
            <p>
              Provider:{" "}
              {formatMarketDataProvider(
                schedule.data_freshness.market_data_provider,
              )}
            </p>
            <p>Status: {schedule.data_freshness.stale ? "Stale" : "Current"}</p>
            {staleHoldings.length > 0 ? (
              <p>Stale holdings: {staleHoldings.join(", ")}</p>
            ) : null}
            {schedule.data_freshness.manual_override_basis ? (
              <p>
                Manual override:{" "}
                {formatManualOverrideBasis(
                  schedule.data_freshness.manual_override_basis,
                )}
              </p>
            ) : null}
          </div>
        </div>
        <div>
          <div className="flex items-center gap-2">
            <Link2 className="h-4 w-4 text-muted" aria-hidden="true" />
            <p className="text-xs text-muted uppercase">Source Links</p>
          </div>
          <ul className="mt-2 space-y-1 text-sm">
            {schedule.source_links.length > 0 ? (
              schedule.source_links.slice(0, 4).map((link) => (
                <li key={link} className="break-words text-xs text-muted">
                  {formatPerformanceSourceLink(link)}
                </li>
              ))
            ) : (
              <li className="text-muted">No source links available</li>
            )}
          </ul>
        </div>
      </div>

      {schedule.notes.length > 0 ? (
        <div className="mt-4">
          <p className="text-xs text-muted uppercase">Notes</p>
          <ul className="mt-2 list-disc pl-5 text-sm text-muted">
            {schedule.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

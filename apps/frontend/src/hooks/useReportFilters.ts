"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";

import { useApiQuery } from "@/hooks/useApiQuery";
import { formatDateInput } from "@/lib/date";
import { isValidReportDate } from "@/lib/reportPackage";
import { REPORT_COVERAGE_QUERY_KEY, SHARED_STALE_MS } from "@/lib/sharedQueries";

/**
 * The report dimensions of Home and `/reports` (#2621 LC, #2548 P1).
 *
 * The URL holds the dimensions:
 *  - `period`: one of the presets. No `period` is the default view: the `1Y` preset with the coverage
 *    bound below. A `period` in the URL, `1Y` too, is an explicit preset with no bound.
 *  - `end`: the last day of the period. No `end` means the period ends today. A future `end` is
 *    allowed: a link to a planned or synthetic period reproduces its dates.
 *  - `start`: the first day of a custom period. A custom period has no preset and no step.
 *  - `currency`: an ISO 4217 code. No `currency` means the base currency of the user.
 *  - `include_restricted=false`: the net worth excludes restricted and illiquid holdings. The
 *    default includes them (`DEFAULT_INCLUDE_RESTRICTED`), so the default figure is the full net worth.
 *  - `tab`: the open tab of `/reports`.
 * A default value is not written to the URL.
 *
 * The cash coverage start bounds only the default view (#2646). `GET /reports/coverage` serves it for
 * the period end: the latest opening position of a cash account. A period that starts earlier fails
 * the cash-flow coverage check, so the default view starts no earlier than that day. The default view
 * thus depends on server data. A link with a `period` or a `start` does not depend on it: with an
 * `end` it reproduces its dates exactly, and without an `end` it ends today. A period that starts
 * before the coverage start shows the coverage blocker.
 */

/**
 * The default restricted-holdings scope of every net worth surface: Home, `/reports` and
 * `/portfolio` (#2645). It equals the default of the API routes. The default net worth includes
 * restricted and illiquid holdings, for example a property, its mortgage and an ESOP.
 */
export const DEFAULT_INCLUDE_RESTRICTED = true;

export const REPORT_PERIOD_PRESETS = ["1M", "1Q", "1Y", "YTD", "3Y", "All"] as const;
export type ReportPeriodPreset = (typeof REPORT_PERIOD_PRESETS)[number];
const DEFAULT_REPORT_PERIOD: ReportPeriodPreset = "1Y";

/** The first day of the `All` period. The ledger has no entry before this date. */
const ALL_PERIOD_START = "2000-01-01";
/** The number of months that one step of previous or next moves a period. */
const PERIOD_STEP_MONTHS: Record<Exclude<ReportPeriodPreset, "All">, number> = {
  "1M": 1,
  "1Q": 3,
  "1Y": 12,
  YTD: 12,
  "3Y": 36,
};

export const REPORT_TABS = [
  { id: "overview", label: "Overview" },
  { id: "balance-sheet", label: "Balance sheet" },
  { id: "income-statement", label: "Income statement" },
  { id: "cash-flow", label: "Cash flow" },
  { id: "package", label: "Full package" },
] as const;
export type ReportTab = (typeof REPORT_TABS)[number]["id"];

/** The URL parameters of the dimensions. A tab link keeps them and changes only `tab`. */
const DIMENSION_PARAMS = ["period", "start", "end", "currency", "include_restricted"] as const;
/** The parameters that a dimension change rewrites: the dimensions and the old route parameters. */
const REPLACED_PARAMS = new Set<string>([...DIMENSION_PARAMS, "start_date", "end_date", "as_of_date"]);

export interface ReportFilters {
  tab: ReportTab;
  /** The preset of the period. Null for a custom period. */
  preset: ReportPeriodPreset | null;
  startDate: string;
  endDate: string;
  /** True when the period ends today. */
  isCurrent: boolean;
  /** The currency in the URL. Undefined means the base currency of the user. */
  currency?: string;
  includeRestricted: boolean;
  /**
   * The date of the opening balance sheet: the day before `startDate`. Null for `All`. When the
   * coverage start bounds the default view, it is that day: the last cash opening balance posts on it.
   */
  openingDate: string | null;
  /** True when the URL has no `period` and no `start`. Only this view applies the coverage bound. */
  isDefaultPeriod: boolean;
  /** True when the coverage start bounds the default view: `startDate` and `openingDate` are that day. */
  opensAtCoverageStart: boolean;
  /**
   * The cash accounts whose opening balance is on the coverage start, when it bounds the default
   * view. Empty otherwise. An opening balance before that day removes the bound of its account.
   */
  coverageLimitingAccounts: readonly string[];
  /** The `end` of the previous period. Null for `All` and for a custom period. */
  previousEnd: string | null;
  /** The `end` of the next period. Null when no next period exists. An empty string is the current period. */
  nextEnd: string | null;
  /** The dimension parameters, without `tab`, as a query string. */
  dimensionQuery: string;
  /**
   * False while the default view waits for the coverage start: it can move `startDate`. A reader of
   * the period does not fetch and shows its loading state until it is true (#2646). An explicit
   * period is ready at once.
   */
  ready: boolean;
}

/** The fields of `GET /reports/coverage` that the default view reads (#2646). */
export interface ReportCoverageViewModel {
  /** `coverage_start`. Null applies no bound. */
  start: string | null;
  /** `limiting_accounts`: the names of the cash accounts whose opening balance is on `start`. */
  limitingAccounts: readonly string[];
}

function toLocalDate(value: string): Date {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day);
}

function dayBefore(value: string): string {
  const date = toLocalDate(value);
  date.setDate(date.getDate() - 1);
  return formatDateInput(date);
}

/** The first and last day of a preset period that ends on `reference`. */
export function resolvePeriodRange(
  preset: ReportPeriodPreset,
  reference: Date,
): { startDate: string; endDate: string } {
  const endDate = formatDateInput(reference);
  const year = reference.getFullYear();
  const month = reference.getMonth();
  if (preset === "All") return { startDate: ALL_PERIOD_START, endDate };
  if (preset === "YTD") return { startDate: formatDateInput(new Date(year, 0, 1)), endDate };
  const months = PERIOD_STEP_MONTHS[preset];
  return { startDate: formatDateInput(new Date(year, month - months + 1, 1)), endDate };
}

function nextPeriodEnd(preset: Exclude<ReportPeriodPreset, "All">, endDate: string, today: string): string {
  const end = toLocalDate(endDate);
  const candidate =
    preset === "YTD"
      ? new Date(end.getFullYear() + 1, 11, 31)
      : new Date(end.getFullYear(), end.getMonth() + PERIOD_STEP_MONTHS[preset] + 1, 0);
  const candidateText = formatDateInput(candidate);
  return candidateText >= today ? "" : candidateText;
}

function isPreset(value: string | null): value is ReportPeriodPreset {
  return (REPORT_PERIOD_PRESETS as readonly string[]).includes(value ?? "");
}

function isTab(value: string | null): value is ReportTab {
  return REPORT_TABS.some((tab) => tab.id === value);
}

/**
 * Read the dimensions from URL parameters. Invalid values fall back to the defaults.
 * `coverage` is the response of `GET /reports/coverage` for the period end. It bounds only the
 * default view. Null, a null start or an invalid date applies no bound.
 */
export function readReportFilters(
  params: Pick<URLSearchParams, "get">,
  now: Date = new Date(),
  coverage: ReportCoverageViewModel | null = null,
): ReportFilters {
  const today = formatDateInput(now);
  const rawTab = params.get("tab");
  const rawPreset = params.get("period");
  // `start_date`, `end_date` and `as_of_date` are the parameters of the old report routes.
  // Their redirects keep the query, so an old link still sets the period.
  const rawEnd = params.get("end") ?? params.get("end_date") ?? params.get("as_of_date") ?? "";
  const end = isValidReportDate(rawEnd) ? rawEnd : "";
  const rawStart = params.get("start") ?? params.get("start_date") ?? "";
  const start = isValidReportDate(rawStart) && rawStart <= (end || today) ? rawStart : "";
  const explicitPreset = !start && isPreset(rawPreset);
  const isDefaultPeriod = !start && !explicitPreset;
  const preset: ReportPeriodPreset | null = start ? null : isPreset(rawPreset) ? rawPreset : DEFAULT_REPORT_PERIOD;
  const rawCurrency = params.get("currency") ?? "";
  const currency = /^[A-Z]{3}$/.test(rawCurrency) ? rawCurrency : undefined;
  const rawIncludeRestricted = params.get("include_restricted");
  const includeRestricted =
    rawIncludeRestricted === "true" ? true : rawIncludeRestricted === "false" ? false : DEFAULT_INCLUDE_RESTRICTED;

  const range = preset
    ? resolvePeriodRange(preset, end ? toLocalDate(end) : now)
    : { startDate: start, endDate: end || today };
  const { endDate } = range;
  const bound =
    isDefaultPeriod && coverage?.start && isValidReportDate(coverage.start) ? coverage.start : null;
  // The default view starts no earlier than the coverage start. An explicit period keeps its start.
  const reachesCoverageStart = bound !== null && range.startDate <= bound && bound <= endDate;
  const startDate = reachesCoverageStart ? bound : range.startDate;
  const openingDate = reachesCoverageStart ? bound : preset === "All" ? null : dayBefore(startDate);
  const steps = preset !== null && preset !== "All";

  const dimensions = new URLSearchParams();
  // An explicit preset stays in the URL, the default preset too: it applies no coverage bound.
  if (explicitPreset && preset) dimensions.set("period", preset);
  if (start) dimensions.set("start", start);
  if (end) dimensions.set("end", end);
  if (currency) dimensions.set("currency", currency);
  if (includeRestricted !== DEFAULT_INCLUDE_RESTRICTED) dimensions.set("include_restricted", String(includeRestricted));

  return {
    tab: isTab(rawTab) ? rawTab : "overview",
    preset,
    startDate,
    endDate,
    isCurrent: !end,
    currency,
    includeRestricted,
    openingDate,
    isDefaultPeriod,
    opensAtCoverageStart: reachesCoverageStart,
    coverageLimitingAccounts: reachesCoverageStart ? (coverage?.limitingAccounts ?? []) : [],
    // The default view has no previous period before the coverage start. An explicit preset steps back.
    previousEnd: steps && !reachesCoverageStart ? dayBefore(startDate) : null,
    nextEnd: steps && end && end < today ? nextPeriodEnd(preset, end, today) : null,
    dimensionQuery: dimensions.toString(),
    ready: true,
  };
}

/** The `/reports` URL of a tab with the given dimension query. */
export function reportsHref(tab: ReportTab, dimensionQuery = ""): string {
  const params = new URLSearchParams(dimensionQuery);
  if (tab !== "overview") params.set("tab", tab);
  const query = params.toString();
  return query ? `/reports?${query}` : "/reports";
}

export interface UseReportFiltersResult extends ReportFilters {
  setPreset: (preset: ReportPeriodPreset) => void;
  /** Set a custom period. The caller keeps the start on or before the end. */
  setCustomPeriod: (startDate: string, endDate: string) => void;
  /** Move to the period that ends on `end`. An empty string moves to the current period. */
  goToPeriodEnd: (end: string) => void;
  setCurrency: (currency: string) => void;
  setIncludeRestricted: (include: boolean) => void;
}

/** The report dimensions of the current URL, and setters that write the URL. */
export function useReportFilters(): UseReportFiltersResult {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const search = searchParams.toString();
  // The bound moves only the start, so the period end and the view kind do not depend on it.
  const { endDate, isDefaultPeriod } = useMemo(() => readReportFilters(new URLSearchParams(search)), [search]);
  // The backend owns the bound: the workflow readiness reads the same date (#2646).
  const coverage = useApiQuery(
    [...REPORT_COVERAGE_QUERY_KEY, endDate],
    "report_coverage_reports_coverage_get",
    { query: { as_of_date: endDate } },
    { staleTime: SHARED_STALE_MS, enabled: isDefaultPeriod },
  );
  const coverageStart = coverage.data?.coverage_start ?? null;
  const limitingAccounts = coverage.data?.limiting_accounts;
  const filters = useMemo(
    () =>
      readReportFilters(new URLSearchParams(search), new Date(), {
        start: coverageStart,
        limitingAccounts: limitingAccounts ?? [],
      }),
    [search, coverageStart, limitingAccounts],
  );

  const update = useCallback(
    (changes: Partial<Record<(typeof DIMENSION_PARAMS)[number], string>>) => {
      const current = new URLSearchParams(search);
      // Start from the canonical dimensions: the parameters of an old route link
      // (`start_date`, `end_date`, `as_of_date`) are already `start` and `end` there.
      const dimensions = new URLSearchParams(filters.dimensionQuery);
      for (const [key, value] of Object.entries(changes)) {
        if (value) dimensions.set(key, value);
        else dimensions.delete(key);
      }
      // One parameter order for every URL: the tab, the dimensions, then the other parameters.
      const ordered = new URLSearchParams();
      const tab = current.get("tab");
      if (tab) ordered.set("tab", tab);
      for (const key of DIMENSION_PARAMS) {
        const value = dimensions.get(key);
        if (value) ordered.set(key, value);
      }
      current.forEach((value, key) => {
        if (!ordered.has(key) && !REPLACED_PARAMS.has(key)) ordered.append(key, value);
      });
      const query = ordered.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [filters.dimensionQuery, pathname, router, search],
  );

  return {
    ...filters,
    // A failed read applies no bound: the reports still load. An explicit period does not wait.
    ready: !isDefaultPeriod || !coverage.isPending,
    // A chosen preset is explicit, the default `1Y` too: it shows its full period (#2646).
    setPreset: useCallback((preset: ReportPeriodPreset) => update({ period: preset, start: "", end: "" }), [update]),
    setCustomPeriod: useCallback(
      (startDate: string, endDate: string) => update({ period: "", start: startDate, end: endDate }),
      [update],
    ),
    goToPeriodEnd: useCallback((end: string) => update({ end }), [update]),
    setCurrency: useCallback((currency: string) => update({ currency }), [update]),
    setIncludeRestricted: useCallback(
      (include: boolean) => update({ include_restricted: include === DEFAULT_INCLUDE_RESTRICTED ? "" : String(include) }),
      [update],
    ),
  };
}

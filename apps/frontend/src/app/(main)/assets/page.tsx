"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/ui/Toast";
import { StatusBadge, TableSkeleton } from "@/components/ui";
import { FilterTabs } from "@/components/ui/FilterTabs";
import { apiOperation } from "@/lib/api-client";
import { formatCurrencyLocale, parseAmount } from "@/lib/audit/money";
import { formatQuantity } from "@/lib/audit/quantity";
import { formatDateDisplay } from "@/lib/date";
import {
  ManagedPosition,
  ManagedPositionListResponse,
  ManualValuationComponentType,
  ManualValuationSource,
  ManualValuationSnapshotListResponse,
  ReconcilePositionsResponse,
} from "@/lib/types";

const STATUS_FILTERS = ["All", "active", "disposed"] as const;
const VALUATION_TYPES: Array<{
  value: ManualValuationComponentType;
  label: string;
}> = [
  { value: "property_value", label: "Property Value" },
  { value: "mortgage_balance", label: "Mortgage Balance" },
  { value: "cpf_balance", label: "CPF / Provident Fund Balance" },
  { value: "retirement_account", label: "Retirement Account" },
  {
    value: "social_security_personal_account",
    label: "Social Security Personal Account",
  },
  { value: "long_term_benefit_asset", label: "Long-term Benefit Asset" },
  { value: "long_term_savings", label: "Long-term Savings" },
  { value: "tax_payable", label: "Tax Payable" },
  { value: "tax_refund", label: "Tax Refund" },
  {
    value: "insurance_cash_value",
    label: "Insurance Cash Value (not coverage)",
  },
  { value: "esop", label: "ESOP" },
  { value: "rsu", label: "RSU" },
  { value: "stock_options", label: "Stock Options" },
  { value: "other_asset", label: "Other Asset" },
  { value: "other_liability", label: "Other Liability" },
];
const VALUATION_SOURCES: Array<{
  value: ManualValuationSource;
  label: string;
}> = [
  { value: "manual", label: "Manual entry" },
  { value: "broker_portal", label: "Broker portal" },
  { value: "bank_portal", label: "Bank portal" },
  { value: "cpf_portal", label: "CPF portal" },
  { value: "tax_portal", label: "Tax portal" },
  { value: "insurer_portal", label: "Insurer portal" },
  { value: "employer_portal", label: "Employer portal" },
  { value: "property_valuation", label: "Property valuation" },
  { value: "other_document", label: "Other source document" },
];
type AmountValue = ReturnType<typeof parseAmount>;

function labelForValuationType(type: ManualValuationComponentType): string {
  return VALUATION_TYPES.find((item) => item.value === type)?.label ?? type;
}

function labelForLiquidityClass(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function labelForValuationSource(source: string): string {
  return (
    VALUATION_SOURCES.find((item) => item.value === source)?.label ?? source
  );
}

export default function AssetsPage() {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [activeFilter, setActiveFilter] =
    useState<(typeof STATUS_FILTERS)[number]>("All");
  const [valuationForm, setValuationForm] = useState({
    component_type: "property_value" as ManualValuationComponentType,
    as_of_date: new Date().toISOString().slice(0, 10),
    value: "",
    currency: "SGD",
    source: "manual" as ManualValuationSource,
    notes: "",
  });

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["positions", activeFilter],
    queryFn: () =>
      apiOperation("list_positions_assets_positions_get", {
        query: {
          status_filter: activeFilter === "All" ? undefined : activeFilter,
        },
      }),
  });

  const { data: valuationData } = useQuery({
    queryKey: ["valuation-snapshots"],
    queryFn: () =>
      apiOperation("list_valuation_snapshots_assets_valuation_snapshots_get", {
        query: { limit: 10 },
      }),
  });

  const reconcileMutation = useMutation({
    mutationFn: () => apiOperation("reconcile_positions_assets_reconcile_post"),
    onSuccess: (result) => {
      const total = result.created + result.updated + result.disposed;
      if (result.skipped > 0) {
        const skippedAssets = result.skipped_assets ?? [];
        const skippedList = skippedAssets.slice(0, 3).join(", ");
        const suffix =
          skippedAssets.length > 3
            ? ` and ${skippedAssets.length - 3} more`
            : "";
        showToast(
          `Reconciled ${total} positions. ${result.skipped} skipped due to incomplete data: ${skippedList}${suffix}`,
          "warning",
        );
      } else {
        showToast(
          `Reconciled ${total} positions (${result.created} created, ${result.updated} updated, ${result.disposed} disposed)`,
          "success",
        );
      }
      queryClient.invalidateQueries({ queryKey: ["positions"] });
    },
    onError: (err: Error) => {
      showToast(`Failed to reconcile: ${err.message}`, "error");
    },
  });

  const createValuationMutation = useMutation({
    mutationFn: () =>
      apiOperation(
        "create_valuation_snapshot_assets_valuation_snapshots_post",
        {
          body: {
            component_type: valuationForm.component_type,
            as_of_date: valuationForm.as_of_date,
            value: valuationForm.value,
            currency: valuationForm.currency,
            source: valuationForm.source,
            notes: valuationForm.notes || null,
          },
        },
      ),
    onSuccess: () => {
      showToast("Manual valuation saved", "success");
      setValuationForm((current) => ({ ...current, value: "", notes: "" }));
      queryClient.invalidateQueries({ queryKey: ["valuation-snapshots"] });
    },
    onError: (err: Error) => {
      showToast(`Failed to save valuation: ${err.message}`, "error");
    },
  });

  const positions = data?.items ?? [];
  const valuationSnapshots = valuationData?.items ?? [];
  const activePositions = positions.filter((p) => p.status === "active");
  const groupedByBroker = positions.reduce(
    (groups, pos) => {
      const broker = pos.account_name ?? "Unknown";
      if (!groups[broker]) groups[broker] = [];
      groups[broker].push(pos);
      return groups;
    },
    {} as Record<string, ManagedPosition[]>,
  );
  const totalsByCurrency = positions.reduce(
    (totals, pos) => {
      const currency = pos.currency || "USD";
      const existing = totals[currency] ?? parseAmount(0);
      totals[currency] = existing.add(parseAmount(pos.cost_basis));
      return totals;
    },
    {} as Record<string, AmountValue>,
  );
  const allocationByCurrency = Object.entries(totalsByCurrency)
    .sort((a, b) => b[1].comparedTo(a[1]))
    .map(([currency, total]) => ({
      currency,
      total,
    }));

  return (
    <div className="p-6">
      <div className="page-header flex items-center justify-between">
        <div>
          <h1 className="page-title">Portfolio Performance</h1>
          <p className="page-description">
            Track your investment holdings and performance across all brokers
          </p>
        </div>
        <button
          onClick={() => reconcileMutation.mutate()}
          disabled={reconcileMutation.isPending}
          className="btn-primary flex items-center gap-2"
        >
          {reconcileMutation.isPending ? (
            <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
          ) : (
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
          )}
          Reconcile Positions
        </button>
      </div>

      {/* Portfolio KPI cards — shown after first load */}
      {!isLoading && !error && positions.length > 0 && (
        <div className="grid gap-4 md:grid-cols-3 mb-6">
          <div className="card p-5">
            <p className="text-xs text-muted uppercase tracking-wide">
              Total Positions
            </p>
            <p className="text-2xl font-semibold mt-1">{positions.length}</p>
            <p className="text-xs text-muted mt-1">
              {Object.keys(groupedByBroker).length} broker
              {Object.keys(groupedByBroker).length !== 1 ? "s" : ""}
            </p>
          </div>
          <div className="card p-5">
            <p className="text-xs text-muted uppercase tracking-wide">
              Active Holdings
            </p>
            <p className="text-2xl font-semibold text-[var(--success)] mt-1">
              {activePositions.length}
            </p>
            <p className="text-xs text-muted mt-1">
              {positions.length - activePositions.length} disposed
            </p>
          </div>
          <div className="card p-5">
            <p className="text-xs text-muted uppercase tracking-wide">
              Total Cost Basis
            </p>
            <p className="text-2xl font-semibold mt-1">
              {allocationByCurrency.map((a, i) => (
                <span key={a.currency} className="block text-xl leading-snug">
                  {i > 0 && <span className="text-base text-muted">+ </span>}
                  {formatCurrencyLocale(a.total.toString(), a.currency)}
                </span>
              ))}
            </p>
            <p className="text-xs text-muted mt-1">
              Book value (no market price yet)
            </p>
          </div>
        </div>
      )}

      {/* Currency allocation breakdown */}
      {!isLoading && !error && allocationByCurrency.length > 1 && (
        <div className="card p-5 mb-6">
          <div className="mb-3">
            <p className="text-xs text-muted uppercase tracking-wide">
              Allocation by Currency
            </p>
            <p className="text-xs text-muted mt-1">
              FX conversion required before cross-currency percentages are
              trusted.
            </p>
          </div>
          <div className="space-y-2">
            {allocationByCurrency.map((a) => (
              <div key={a.currency} className="flex items-center gap-3">
                <span className="w-10 text-xs font-mono font-medium text-right">
                  {a.currency}
                </span>
                <div className="flex-1 h-2 rounded-full bg-[var(--background-muted)] overflow-hidden">
                  <div
                    className="h-full rounded-full bg-[var(--accent)]"
                    style={{ width: "100%" }}
                  />
                </div>
                <span className="text-xs text-muted">
                  {formatCurrencyLocale(a.total.toString(), a.currency)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card p-5 mb-6">
        <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-5">
          <div className="flex-1">
            <p className="text-xs text-muted uppercase tracking-wide">
              Manual Valuations
            </p>
            <h2 className="font-semibold mt-1 mb-2">
              Property, retirement benefits, tax, insurance cash value, and
              equity awards
            </h2>
            <p className="text-xs text-muted mb-4">
              For ESOP/RSU, property, and liability records, use the{" "}
              <Link
                href="/portfolio/evidence"
                className="text-[var(--accent)] underline"
              >
                guided evidence intake
              </Link>{" "}
              to capture a structured valuation basis and source anchor.
            </p>
            {valuationSnapshots.length ? (
              <div className="divide-y divide-[var(--border)]">
                {valuationSnapshots.slice(0, 5).map((snapshot) => (
                  <div
                    key={snapshot.id}
                    className="py-3 flex items-center justify-between gap-3"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium">
                          {labelForValuationType(snapshot.component_type)}
                        </span>
                        <span className="badge badge-muted">
                          {labelForLiquidityClass(snapshot.liquidity_class)}
                        </span>
                      </div>
                      <p className="text-xs text-muted mt-0.5">
                        {formatDateDisplay(snapshot.as_of_date)} ·{" "}
                        {labelForValuationSource(snapshot.source)}
                      </p>
                    </div>
                    <div className="text-right font-semibold">
                      {formatCurrencyLocale(snapshot.value, snapshot.currency)}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted">
                No manual valuation snapshots recorded.
              </p>
            )}
          </div>
          <form
            className="grid gap-3 lg:w-[24rem]"
            onSubmit={(event) => {
              event.preventDefault();
              createValuationMutation.mutate();
            }}
          >
            <div className="grid gap-1">
              <label
                htmlFor="valuation-type"
                className="text-xs font-medium text-muted"
              >
                Valuation type
              </label>
              <select
                id="valuation-type"
                className="input"
                value={valuationForm.component_type}
                onChange={(event) =>
                  setValuationForm((current) => ({
                    ...current,
                    component_type: event.target
                      .value as ManualValuationComponentType,
                  }))
                }
              >
                {VALUATION_TYPES.map((type) => (
                  <option key={type.value} value={type.value}>
                    {type.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="grid gap-1">
                <label
                  htmlFor="valuation-date"
                  className="text-xs font-medium text-muted"
                >
                  As of date
                </label>
                <input
                  id="valuation-date"
                  type="date"
                  className="input"
                  value={valuationForm.as_of_date}
                  onChange={(event) =>
                    setValuationForm((current) => ({
                      ...current,
                      as_of_date: event.target.value,
                    }))
                  }
                  required
                />
              </div>
              <div className="grid gap-1">
                <label
                  htmlFor="valuation-currency"
                  className="text-xs font-medium text-muted"
                >
                  Currency
                </label>
                <input
                  id="valuation-currency"
                  className="input uppercase"
                  maxLength={3}
                  value={valuationForm.currency}
                  onChange={(event) =>
                    setValuationForm((current) => ({
                      ...current,
                      currency: event.target.value.toUpperCase(),
                    }))
                  }
                  required
                />
              </div>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="grid gap-1">
                <label
                  htmlFor="valuation-value"
                  className="text-xs font-medium text-muted"
                >
                  Value
                </label>
                <input
                  id="valuation-value"
                  inputMode="decimal"
                  className="input"
                  value={valuationForm.value}
                  onChange={(event) =>
                    setValuationForm((current) => ({
                      ...current,
                      value: event.target.value,
                    }))
                  }
                  required
                />
              </div>
              <div className="grid gap-1">
                <label
                  htmlFor="valuation-source"
                  className="text-xs font-medium text-muted"
                >
                  Source
                </label>
                <select
                  id="valuation-source"
                  className="input"
                  value={valuationForm.source}
                  onChange={(event) =>
                    setValuationForm((current) => ({
                      ...current,
                      source: event.target.value as ManualValuationSource,
                    }))
                  }
                  required
                >
                  {VALUATION_SOURCES.map((source) => (
                    <option key={source.value} value={source.value}>
                      {source.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="grid gap-1">
              <label
                htmlFor="valuation-notes"
                className="text-xs font-medium text-muted"
              >
                Notes
              </label>
              <input
                id="valuation-notes"
                className="input"
                value={valuationForm.notes}
                onChange={(event) =>
                  setValuationForm((current) => ({
                    ...current,
                    notes: event.target.value,
                  }))
                }
              />
            </div>
            <button
              type="submit"
              className="btn-primary"
              disabled={createValuationMutation.isPending}
            >
              {createValuationMutation.isPending
                ? "Saving..."
                : "Add valuation"}
            </button>
          </form>
        </div>
      </div>

      <div className="flex items-center justify-between mb-6">
        <FilterTabs
          options={STATUS_FILTERS}
          value={activeFilter}
          onChange={setActiveFilter}
          capitalize
          ariaLabel="Asset status filter"
        />

        {!isLoading && !error && positions.length > 0 && (
          <div className="text-sm text-muted">
            Total Value:{" "}
            <span className="font-semibold text-[var(--foreground)]">
              {Object.entries(totalsByCurrency).map(([currency, total], i) => (
                <span key={currency}>
                  {i > 0 && " + "}
                  {formatCurrencyLocale(total.toString(), currency)}
                </span>
              ))}
            </span>
          </div>
        )}
      </div>

      {error && (
        <div className="mb-4 alert-error">
          {error instanceof Error ? error.message : "Failed to load positions"}
        </div>
      )}

      {isLoading ? (
        <TableSkeleton label="Loading positions" rows={4} columns={3} />
      ) : error ? (
        <div className="card p-8 text-center" role="alert" aria-live="polite">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-[var(--error-muted)] text-[var(--error)] mb-4">
            <svg
              className="w-6 h-6"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
          </div>
          <p className="text-[var(--foreground)] font-medium mb-2">
            Failed to load positions
          </p>
          <p className="text-sm text-muted mb-6">
            {error instanceof Error ? error.message : "Unknown error"}
          </p>
          <button
            onClick={() => refetch()}
            className="btn-secondary"
            aria-label="Retry loading positions"
          >
            Retry
          </button>
        </div>
      ) : positions.length === 0 ? (
        <div className="card p-8 text-center">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-[var(--background-muted)] text-muted mb-4">
            <svg
              className="w-6 h-6"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"
              />
            </svg>
          </div>
          <p className="text-muted mb-4">No positions found</p>
          <p className="text-sm text-muted mb-6">
            Upload brokerage statements and run reconciliation to see your
            holdings here.
          </p>
          <button
            onClick={() => reconcileMutation.mutate()}
            className="btn-primary"
            disabled={reconcileMutation.isPending}
          >
            Run Reconciliation
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          {Object.entries(groupedByBroker).map(([broker, brokerPositions]) => {
            const brokerTotalsByCurrency = brokerPositions.reduce(
              (totals, p) => {
                const currency = p.currency || "USD";
                const existing = totals[currency] ?? parseAmount(0);
                totals[currency] = existing.add(parseAmount(p.cost_basis));
                return totals;
              },
              {} as Record<string, AmountValue>,
            );
            return (
              <div key={broker} className="card">
                <div className="card-header flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="badge badge-primary">{broker}</span>
                    <span className="text-xs text-muted">
                      {brokerPositions.length} positions
                    </span>
                  </div>
                  <span className="text-sm font-medium">
                    {Object.entries(brokerTotalsByCurrency).map(
                      ([currency, total], i) => (
                        <span key={currency}>
                          {i > 0 && " + "}
                          {formatCurrencyLocale(total.toString(), currency)}
                        </span>
                      ),
                    )}
                  </span>
                </div>
                <div className="divide-y divide-[var(--border)]">
                  {brokerPositions.map((position) => (
                    <div
                      key={position.id}
                      className="px-6 py-3 flex items-center justify-between hover:bg-[var(--background-muted)]/50 transition-colors"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-medium font-mono">
                            {position.asset_identifier}
                          </span>
                          <StatusBadge
                            status={position.status}
                            variants={{ active: "success" }}
                          />
                        </div>
                        <div className="text-xs text-muted mt-0.5">
                          Acquired:{" "}
                          {formatDateDisplay(position.acquisition_date)}
                          {position.disposal_date &&
                            ` | Disposed: ${formatDateDisplay(position.disposal_date)}`}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="font-semibold">
                          {formatQuantity(position.quantity)} units
                        </div>
                        <div className="text-sm text-muted">
                          {formatCurrencyLocale(
                            position.cost_basis,
                            position.currency,
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

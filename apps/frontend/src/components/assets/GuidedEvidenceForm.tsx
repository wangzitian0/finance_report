"use client";

/**
 * Shared guided evidence intake form (EPIC-011 AC11.9.6–AC11.9.9, issue #706).
 *
 * Provides one structured, auditable flow for the three long-tail source
 * classes that v1 does not reliably auto-parse: ESOP/RSU plans, property
 * statements, and liability statements. It captures value/amount, currency,
 * as-of date, a structured valuation basis, a source label + anchor, and
 * notes, then persists the evidence through the EXISTING manual-valuation API
 * (`POST /api/assets/valuation-snapshots`) via the typed `lib/api.ts` client.
 *
 * Money is carried as a Decimal-safe string end-to-end — there is no float
 * arithmetic on the frontend; the raw string is forwarded to the backend,
 * which owns Decimal validation.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui";
import { useToast } from "@/components/ui/Toast";
import { apiOperation } from "@/lib/api-client";
import { formatCurrencyLocale } from "@/lib/audit/money";
import { formatDateDisplay, formatDateInput } from "@/lib/date";
import type {
  ManualValuationBasis,
  ManualValuationComponentType,
  ManualValuationSnapshot,
  ManualValuationSnapshotListResponse,
} from "@/lib/types";

/** The three guided source classes from issue #706. */
export type EvidenceSourceClass =
  "esop_rsu_plan" | "property_statement" | "liability_statement";

interface SourceClassConfig {
  value: EvidenceSourceClass;
  label: string;
  /** Maps the guided source class to the backend manual-valuation component. */
  componentType: ManualValuationComponentType;
  /** Helper copy shown under the source-class selector. */
  hint: string;
  /** A sensible default valuation basis for this source class. */
  defaultBasis: ManualValuationBasis;
}

export const SOURCE_CLASS_CONFIGS: SourceClassConfig[] = [
  {
    value: "esop_rsu_plan",
    label: "ESOP / RSU plan",
    componentType: "rsu",
    hint: "Restricted equity awards — grant or vesting statements.",
    defaultBasis: "employer_grant_document",
  },
  {
    value: "property_statement",
    label: "Property statement",
    componentType: "property_value",
    hint: "Real estate valuations or appraisals.",
    defaultBasis: "market_appraisal",
  },
  {
    value: "liability_statement",
    label: "Liability statement",
    componentType: "other_liability",
    hint: "Loans, mortgages, or other outstanding balances.",
    defaultBasis: "bank_statement",
  },
];

export const VALUATION_BASIS_OPTIONS: Array<{
  value: ManualValuationBasis;
  label: string;
}> = [
  { value: "market_appraisal", label: "Market appraisal" },
  { value: "broker_statement", label: "Broker statement" },
  { value: "employer_grant_document", label: "Employer grant document" },
  { value: "bank_statement", label: "Bank statement" },
  { value: "government_statement", label: "Government statement" },
  { value: "insurer_statement", label: "Insurer statement" },
  { value: "self_estimate", label: "Self estimate" },
];

function configForSourceClass(value: EvidenceSourceClass): SourceClassConfig {
  return (
    SOURCE_CLASS_CONFIGS.find((config) => config.value === value) ??
    SOURCE_CLASS_CONFIGS[0]
  );
}

interface EvidenceFormState {
  source_class: EvidenceSourceClass;
  value: string;
  currency: string;
  as_of_date: string;
  valuation_basis: ManualValuationBasis | "";
  source_label: string;
  source_anchor: string;
  notes: string;
}

function initialFormState(): EvidenceFormState {
  const defaultClass = SOURCE_CLASS_CONFIGS[0];
  return {
    source_class: defaultClass.value,
    value: "",
    currency: "SGD",
    as_of_date: formatDateInput(new Date()),
    valuation_basis: defaultClass.defaultBasis,
    source_label: "",
    source_anchor: "",
    notes: "",
  };
}

interface FieldErrors {
  value?: string;
  as_of_date?: string;
  valuation_basis?: string;
  source_label?: string;
}

/**
 * Decimal string-format check for the monetary value. Validated as a string,
 * never via JS number conversion (`Number()`/`parseFloat()`), per the frontend
 * monetary rule in apps/frontend/frontend-patterns.md §7. Accepts an optional
 * leading minus, digits, and an optional fractional part; rejects empty,
 * non-numeric, and `Infinity`/`NaN` inputs.
 */
const DECIMAL_STRING_PATTERN = /^-?\d+(\.\d+)?$/;

/**
 * A positive monetary amount must match the decimal format and be strictly
 * greater than zero. Zero and negative values are rejected as readiness
 * blockers. The "greater than zero" check is performed on the string form
 * (sign + all-zero digits) so no float conversion is involved.
 */
function isPositiveDecimalString(raw: string): boolean {
  const trimmed = raw.trim();
  if (!DECIMAL_STRING_PATTERN.test(trimmed)) {
    return false;
  }
  if (trimmed.startsWith("-")) {
    return false;
  }
  // Reject all-zero amounts (e.g. "0", "0.00") without numeric conversion.
  return /[1-9]/.test(trimmed);
}

/**
 * Validate the guided evidence form. Returns per-field errors plus a flat list
 * of readiness blockers; the form refuses to call the API while any blocker is
 * present (AC11.9.6).
 */
export function validateEvidenceForm(state: EvidenceFormState): {
  errors: FieldErrors;
  blockers: string[];
} {
  const errors: FieldErrors = {};
  const blockers: string[] = [];

  if (!isPositiveDecimalString(state.value)) {
    errors.value = "Enter a positive numeric amount";
    blockers.push("missing_value");
  }

  if (!state.as_of_date) {
    errors.as_of_date = "As-of date is required";
    blockers.push("missing_as_of_date");
  }

  if (!state.valuation_basis) {
    errors.valuation_basis = "Valuation basis is required";
    blockers.push("missing_valuation_basis");
  }

  if (!state.source_label.trim()) {
    errors.source_label = "Source label is required";
    blockers.push("missing_source_label");
  }

  return { errors, blockers };
}

interface GuidedEvidenceFormProps {
  /** Optional initial source class so callers can deep-link a flow. */
  initialSourceClass?: EvidenceSourceClass;
}

export default function GuidedEvidenceForm({
  initialSourceClass,
}: GuidedEvidenceFormProps) {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<EvidenceFormState>(() => {
    const base = initialFormState();
    if (!initialSourceClass) return base;
    const config = configForSourceClass(initialSourceClass);
    return {
      ...base,
      source_class: config.value,
      valuation_basis: config.defaultBasis,
    };
  });
  const [submitted, setSubmitted] = useState(false);

  const { errors, blockers } = useMemo(
    () => validateEvidenceForm(form),
    [form],
  );
  const activeConfig = configForSourceClass(form.source_class);

  const { data: snapshotData } = useQuery({
    queryKey: ["valuation-snapshots", "guided-evidence"],
    queryFn: () =>
      apiOperation("list_valuation_snapshots_assets_valuation_snapshots_get", {
        query: { limit: 10 },
      }),
  });

  const recentEvidence: ManualValuationSnapshot[] = snapshotData?.items ?? [];

  const createMutation = useMutation({
    mutationFn: () => {
      // Compose a stable source label that carries the anchor for the
      // traceability appendix when one is provided.
      const sourceLabel = form.source_anchor.trim()
        ? `${form.source_label.trim()} (${form.source_anchor.trim()})`
        : form.source_label.trim();
      return apiOperation(
        "create_valuation_snapshot_assets_valuation_snapshots_post",
        {
          body: {
            component_type: activeConfig.componentType,
            as_of_date: form.as_of_date,
            // Decimal-safe: forward the raw trimmed string, no float math.
            value: form.value.trim(),
            currency: form.currency,
            source: sourceLabel,
            valuation_basis: form.valuation_basis || null,
            notes: form.notes.trim() || null,
          },
        },
      );
    },
    onSuccess: () => {
      showToast("Evidence saved", "success");
      setSubmitted(false);
      setForm((current) => ({
        ...initialFormState(),
        source_class: current.source_class,
        currency: current.currency,
        valuation_basis: configForSourceClass(current.source_class)
          .defaultBasis,
      }));
      queryClient.invalidateQueries({ queryKey: ["valuation-snapshots"] });
    },
    onError: (err: Error) => {
      showToast(`Failed to save evidence: ${err.message}`, "error");
    },
  });

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (blockers.length > 0) {
      return;
    }
    createMutation.mutate();
  };

  const showError = (field: keyof FieldErrors): string | undefined =>
    submitted ? errors[field] : undefined;

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <form
        className="card p-5 grid gap-4"
        aria-label="Guided evidence form"
        onSubmit={handleSubmit}
        noValidate
      >
        <div>
          <div className="flex items-center gap-2">
            <h2 className="font-semibold">Guided evidence intake</h2>
            <Badge variant="warning" data-testid="manual-trusted-badge">
              Manual-trusted
            </Badge>
          </div>
          <p className="text-xs text-muted mt-1">
            Structured evidence with a source anchor. Manually entered values
            are labelled manual-trusted in reports and the traceability
            appendix.
          </p>
        </div>

        <div className="grid gap-1">
          <label
            htmlFor="evidence-source-class"
            className="text-xs font-medium text-muted"
          >
            Source class
          </label>
          <select
            id="evidence-source-class"
            className="input"
            value={form.source_class}
            onChange={(event) => {
              const next = event.target.value as EvidenceSourceClass;
              setForm((current) => ({
                ...current,
                source_class: next,
                valuation_basis: configForSourceClass(next).defaultBasis,
              }));
            }}
          >
            {SOURCE_CLASS_CONFIGS.map((config) => (
              <option key={config.value} value={config.value}>
                {config.label}
              </option>
            ))}
          </select>
          <p className="text-xs text-muted">{activeConfig.hint}</p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="grid gap-1">
            <label
              htmlFor="evidence-value"
              className="text-xs font-medium text-muted"
            >
              Value / amount
            </label>
            <input
              id="evidence-value"
              inputMode="decimal"
              className="input"
              value={form.value}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  value: event.target.value,
                }))
              }
              aria-invalid={Boolean(showError("value"))}
            />
            {showError("value") && (
              <p className="text-xs text-[var(--error)]" role="alert">
                {errors.value}
              </p>
            )}
          </div>
          <div className="grid gap-1">
            <label
              htmlFor="evidence-currency"
              className="text-xs font-medium text-muted"
            >
              Currency
            </label>
            <input
              id="evidence-currency"
              className="input uppercase"
              maxLength={3}
              value={form.currency}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  currency: event.target.value.toUpperCase(),
                }))
              }
            />
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="grid gap-1">
            <label
              htmlFor="evidence-as-of"
              className="text-xs font-medium text-muted"
            >
              As-of date
            </label>
            <input
              id="evidence-as-of"
              type="date"
              className="input"
              value={form.as_of_date}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  as_of_date: event.target.value,
                }))
              }
              aria-invalid={Boolean(showError("as_of_date"))}
            />
            {showError("as_of_date") && (
              <p className="text-xs text-[var(--error)]" role="alert">
                {errors.as_of_date}
              </p>
            )}
          </div>
          <div className="grid gap-1">
            <label
              htmlFor="evidence-basis"
              className="text-xs font-medium text-muted"
            >
              Valuation basis
            </label>
            <select
              id="evidence-basis"
              className="input"
              value={form.valuation_basis}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  valuation_basis: event.target.value as
                    ManualValuationBasis | "",
                }))
              }
              aria-invalid={Boolean(showError("valuation_basis"))}
            >
              <option value="">Select a basis…</option>
              {VALUATION_BASIS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            {showError("valuation_basis") && (
              <p className="text-xs text-[var(--error)]" role="alert">
                {errors.valuation_basis}
              </p>
            )}
          </div>
        </div>

        <div className="grid gap-1">
          <label
            htmlFor="evidence-source-label"
            className="text-xs font-medium text-muted"
          >
            Source label
          </label>
          <input
            id="evidence-source-label"
            className="input"
            placeholder="e.g. Acme RSU grant 2026"
            value={form.source_label}
            onChange={(event) =>
              setForm((current) => ({
                ...current,
                source_label: event.target.value,
              }))
            }
            aria-invalid={Boolean(showError("source_label"))}
          />
          {showError("source_label") && (
            <p className="text-xs text-[var(--error)]" role="alert">
              {errors.source_label}
            </p>
          )}
        </div>

        <div className="grid gap-1">
          <label
            htmlFor="evidence-source-anchor"
            className="text-xs font-medium text-muted"
          >
            Source anchor (optional)
          </label>
          <input
            id="evidence-source-anchor"
            className="input"
            placeholder="Document reference, page, or URL"
            value={form.source_anchor}
            onChange={(event) =>
              setForm((current) => ({
                ...current,
                source_anchor: event.target.value,
              }))
            }
          />
        </div>

        <div className="grid gap-1">
          <label
            htmlFor="evidence-notes"
            className="text-xs font-medium text-muted"
          >
            Notes (optional)
          </label>
          <input
            id="evidence-notes"
            className="input"
            value={form.notes}
            onChange={(event) =>
              setForm((current) => ({ ...current, notes: event.target.value }))
            }
          />
        </div>

        {submitted && blockers.length > 0 && (
          <div
            className="alert-error"
            role="alert"
            data-testid="evidence-readiness-blocker"
          >
            Resolve the highlighted fields before saving. Missing a valuation
            basis or as-of date blocks report readiness.
          </div>
        )}

        <button
          type="submit"
          className="btn-primary"
          disabled={createMutation.isPending}
        >
          {createMutation.isPending ? "Saving…" : "Save evidence"}
        </button>
      </form>

      <div className="card p-5" data-testid="recent-evidence-panel">
        <p className="text-xs text-muted uppercase tracking-wide">
          Recent evidence
        </p>
        <h2 className="font-semibold mt-1 mb-4">Manually entered records</h2>
        {recentEvidence.length ? (
          <ul className="divide-y divide-[var(--border)]">
            {recentEvidence.map((snapshot) => (
              <li
                key={snapshot.id}
                className="py-3 flex items-center justify-between gap-3"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium">{snapshot.source}</span>
                    <Badge variant="warning">Manual-trusted</Badge>
                  </div>
                  <p className="text-xs text-muted mt-0.5">
                    {formatDateDisplay(snapshot.as_of_date)}
                    {snapshot.valuation_basis
                      ? ` · ${snapshot.valuation_basis.replace(/_/g, " ")}`
                      : ""}
                  </p>
                </div>
                <div className="text-right font-semibold">
                  {formatCurrencyLocale(snapshot.value, snapshot.currency)}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">No evidence recorded yet.</p>
        )}
      </div>
    </div>
  );
}

"use client";

import { useId, useState } from "react";

import {
  COCKPIT_PERIOD_PRESETS,
  COCKPIT_PERIOD_STORAGE_KEY,
  resolvePeriodRange,
  type CockpitPeriodPreset,
} from "@/components/home/ThreeStatementNav";

/**
 * Reusable report filter controls (Slice 3 of #751).
 *
 * The labelled date input and currency `<select>` were duplicated across every
 * report route. These primitives keep the exact markup/classes the routes used
 * (`input w-auto`, uppercase muted label) while emitting plain string values so
 * routes can wire them to `useReportFilters` state.
 */

interface DateFilterControlProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
}

export function DateFilterControl({ label, value, onChange }: DateFilterControlProps) {
  const id = useId();
  return (
    <label htmlFor={id} className="flex flex-col gap-1">
      <span className="text-xs text-muted uppercase">{label}</span>
      <input
        id={id}
        type="date"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="input w-auto"
      />
    </label>
  );
}

interface CurrencyFilterControlProps {
  value: string;
  currencies: string[];
  onChange: (value: string) => void;
  label?: string;
}

export function CurrencyFilterControl({
  value,
  currencies,
  onChange,
  label = "Currency",
}: CurrencyFilterControlProps) {
  const id = useId();
  return (
    <label htmlFor={id} className="flex flex-col gap-1">
      <span className="text-xs text-muted uppercase">{label}</span>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="input w-auto"
      >
        {currencies.map((currency) => (
          <option key={currency} value={currency}>
            {currency}
          </option>
        ))}
      </select>
    </label>
  );
}

interface PeriodPresetFilterControlProps {
  onSelectRange: (
    range: { startDate: string; endDate: string },
    preset: CockpitPeriodPreset,
  ) => void;
  defaultPreset?: CockpitPeriodPreset;
}

function readStoredPreset(
  fallback: CockpitPeriodPreset,
): CockpitPeriodPreset {
  try {
    const stored = window.sessionStorage.getItem(COCKPIT_PERIOD_STORAGE_KEY);
    if (
      stored &&
      (COCKPIT_PERIOD_PRESETS as readonly string[]).includes(stored)
    ) {
      return stored as CockpitPeriodPreset;
    }
  } catch {
    // Ignore storage read errors in restricted environments.
  }
  return fallback;
}

export function PeriodPresetFilterControl({
  onSelectRange,
  defaultPreset = "1Y",
}: PeriodPresetFilterControlProps) {
  const [activePreset, setActivePreset] = useState<CockpitPeriodPreset>(() =>
    readStoredPreset(defaultPreset),
  );

  const handleSelect = (preset: CockpitPeriodPreset) => {
    setActivePreset(preset);
    try {
      window.sessionStorage.setItem(COCKPIT_PERIOD_STORAGE_KEY, preset);
    } catch {
      // Ignore storage write errors in restricted environments.
    }
    onSelectRange(resolvePeriodRange(preset), preset);
  };

  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-muted uppercase">Quick period</span>
      <div
        role="group"
        aria-label="Reporting period"
        className="inline-flex flex-wrap items-center gap-1 rounded-lg bg-[var(--background-muted)] p-1"
      >
        {COCKPIT_PERIOD_PRESETS.map((preset) => {
          const active = activePreset === preset;
          return (
            <button
              key={preset}
              type="button"
              aria-label={`Period ${preset}`}
              aria-pressed={active}
              onClick={() => handleSelect(preset)}
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
  );
}

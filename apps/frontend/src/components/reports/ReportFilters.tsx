"use client";

import { useId } from "react";

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

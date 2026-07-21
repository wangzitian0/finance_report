"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useToast } from "@/components/ui/Toast";
import { apiOperation } from "@/lib/api-client";
import { PriceUpdate, PriceUpdateResponse } from "@/lib/types";

interface PriceRow {
  asset_identifier: string;
  price: string;
  currency: string;
  price_date: string;
}

function todayStr(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const EMPTY_ROW: PriceRow = {
  asset_identifier: "",
  price: "",
  currency: "USD",
  price_date: todayStr(),
};

interface PriceUpdateFormProps {
  /** Pre-filled tickers from holdings, so user can pick from them */
  knownTickers?: string[];
  onSuccess?: () => void;
}

export function PriceUpdateForm({
  knownTickers = [],
  onSuccess,
}: PriceUpdateFormProps) {
  const { showToast } = useToast();
  const [rows, setRows] = useState<PriceRow[]>([{ ...EMPTY_ROW }]);

  const mutation = useMutation({
    mutationFn: (updates: PriceUpdate[]) =>
      apiOperation("update_prices_portfolio_prices_update_post", {
        body: { updates },
      }),
    onSuccess: (result) => {
      showToast(`Updated ${result.updated_count} price(s)`, "success");
      setRows([{ ...EMPTY_ROW }]);
      onSuccess?.();
    },
    onError: (err: Error) => {
      showToast(`Failed: ${err.message}`, "error");
    },
  });

  const updateRow = (index: number, field: keyof PriceRow, value: string) => {
    setRows((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: value };
      return next;
    });
  };

  const addRow = () => setRows((prev) => [...prev, { ...EMPTY_ROW }]);

  const removeRow = (index: number) => {
    setRows((prev) =>
      prev.length <= 1 ? prev : prev.filter((_, i) => i !== index),
    );
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    const valid = rows.filter(
      (r) => r.asset_identifier.trim() && r.price.trim(),
    );
    if (valid.length === 0) {
      showToast("Add at least one price update", "error");
      return;
    }

    const updates: PriceUpdate[] = valid.map((r) => ({
      asset_identifier: r.asset_identifier.trim(),
      price: r.price.trim(),
      currency: r.currency.trim() || "USD",
      price_date: r.price_date,
    }));

    mutation.mutate(updates);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-3">
        {rows.map((row, index) => (
          <div key={index} className="flex items-end gap-3">
            <div className="flex-1">
              <label className="block text-xs text-muted mb-1">
                {index === 0 ? "Ticker / Asset" : ""}
              </label>
              {knownTickers.length > 0 ? (
                <select
                  value={row.asset_identifier}
                  onChange={(e) =>
                    updateRow(index, "asset_identifier", e.target.value)
                  }
                  className="input"
                  required
                >
                  <option value="">Select asset...</option>
                  {knownTickers.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  value={row.asset_identifier}
                  onChange={(e) =>
                    updateRow(index, "asset_identifier", e.target.value)
                  }
                  placeholder="AAPL, MSFT..."
                  className="input"
                  required
                />
              )}
            </div>
            <div className="w-32">
              <label className="block text-xs text-muted mb-1">
                {index === 0 ? "Price" : ""}
              </label>
              <input
                type="number"
                step="0.01"
                min="0"
                value={row.price}
                onChange={(e) => updateRow(index, "price", e.target.value)}
                placeholder="0.00"
                className="input"
                required
              />
            </div>
            <div className="w-20">
              <label className="block text-xs text-muted mb-1">
                {index === 0 ? "CCY" : ""}
              </label>
              <input
                type="text"
                maxLength={3}
                value={row.currency}
                onChange={(e) =>
                  updateRow(index, "currency", e.target.value.toUpperCase())
                }
                className="input uppercase"
                required
              />
            </div>
            <div className="w-36">
              <label className="block text-xs text-muted mb-1">
                {index === 0 ? "Date" : ""}
              </label>
              <input
                type="date"
                value={row.price_date}
                onChange={(e) => updateRow(index, "price_date", e.target.value)}
                className="input"
                required
              />
            </div>
            <button
              type="button"
              onClick={() => removeRow(index)}
              className="p-2 text-muted hover:text-[var(--error)] transition-colors"
              aria-label="Remove row"
              disabled={rows.length <= 1}
            >
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
                  d="M6 18L18 6M6 6l12 12"
                />
              </svg>
            </button>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between pt-2">
        <button
          type="button"
          onClick={addRow}
          className="btn-ghost text-sm flex items-center gap-1"
        >
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
              d="M12 4v16m8-8H4"
            />
          </svg>
          Add Row
        </button>
        <button
          type="submit"
          disabled={mutation.isPending}
          className="btn-primary flex items-center gap-2"
        >
          {mutation.isPending && (
            <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
          )}
          Update Prices
        </button>
      </div>
    </form>
  );
}

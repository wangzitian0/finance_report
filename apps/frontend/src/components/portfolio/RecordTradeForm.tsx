"use client";

import { useState } from "react";
import { apiOperation } from "@/lib/api";

type CostBasisMethodValue = "FIFO" | "LIFO" | "AvgCost";

export function RecordTradeForm({
  knownTickers = [],
  defaultCurrency = "SGD",
  onSuccess,
}: {
  knownTickers?: string[];
  defaultCurrency?: string;
  onSuccess: () => void;
}) {
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [transactionDate, setTransactionDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [assetIdentifier, setAssetIdentifier] = useState("");
  const [quantity, setQuantity] = useState("");
  const [unitPrice, setUnitPrice] = useState("");
  const [currency, setCurrency] = useState(defaultCurrency);
  const [fees, setFees] = useState("0.00");
  const [costBasisMethod, setCostBasisMethod] = useState<CostBasisMethodValue>("FIFO");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const ticker = assetIdentifier.trim().toUpperCase();
    const ccy = currency.trim().toUpperCase();
    if (!ticker || !transactionDate || !quantity.trim() || !unitPrice.trim() || ccy.length !== 3) {
      setError("Enter date, ticker, quantity, unit price, and a 3-letter currency code.");
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      await apiOperation("record_portfolio_trade_portfolio_trades_post", {
        body: {
          side,
          transaction_date: transactionDate,
          asset_identifier: ticker,
          quantity: quantity.trim(),
          unit_price: unitPrice.trim(),
          currency: ccy,
          fees: fees.trim() || "0.00",
          cost_basis_method: costBasisMethod,
        },
      });
      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to record trade");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <div role="alert" className="rounded border border-[var(--error)] bg-[var(--error-muted)] px-3 py-2 text-sm text-[var(--error)]">
          {error}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="mb-1 block text-xs font-medium uppercase text-muted">Side</span>
          <select
            aria-label="Trade side"
            value={side}
            onChange={(e) => setSide(e.target.value as "BUY" | "SELL")}
            className="w-full rounded border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm"
          >
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>
        </label>

        <label className="block text-sm">
          <span className="mb-1 block text-xs font-medium uppercase text-muted">Trade date</span>
          <input
            type="date"
            aria-label="Trade date"
            value={transactionDate}
            onChange={(e) => setTransactionDate(e.target.value)}
            className="w-full rounded border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm"
          />
        </label>

        <label className="block text-sm">
          <span className="mb-1 block text-xs font-medium uppercase text-muted">Ticker</span>
          <input
            type="text"
            aria-label="Ticker"
            list="portfolio-known-tickers"
            placeholder="AAPL"
            value={assetIdentifier}
            onChange={(e) => setAssetIdentifier(e.target.value)}
            className="w-full rounded border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm"
          />
          {knownTickers.length > 0 && (
            <datalist id="portfolio-known-tickers">
              {knownTickers.map((t) => (
                <option key={t} value={t} />
              ))}
            </datalist>
          )}
        </label>

        <label className="block text-sm">
          <span className="mb-1 block text-xs font-medium uppercase text-muted">Currency</span>
          <input
            type="text"
            aria-label="Trade currency"
            maxLength={3}
            value={currency}
            onChange={(e) => setCurrency(e.target.value.toUpperCase())}
            className="w-full rounded border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm uppercase"
          />
        </label>

        <label className="block text-sm">
          <span className="mb-1 block text-xs font-medium uppercase text-muted">Quantity</span>
          <input
            type="text"
            inputMode="decimal"
            aria-label="Quantity"
            placeholder="10"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            className="w-full rounded border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm"
          />
        </label>

        <label className="block text-sm">
          <span className="mb-1 block text-xs font-medium uppercase text-muted">Unit price</span>
          <input
            type="text"
            inputMode="decimal"
            aria-label="Unit price"
            placeholder="100.00"
            value={unitPrice}
            onChange={(e) => setUnitPrice(e.target.value)}
            className="w-full rounded border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm"
          />
        </label>

        <label className="block text-sm">
          <span className="mb-1 block text-xs font-medium uppercase text-muted">Fees</span>
          <input
            type="text"
            inputMode="decimal"
            aria-label="Fees"
            value={fees}
            onChange={(e) => setFees(e.target.value)}
            className="w-full rounded border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm"
          />
        </label>

        <label className="block text-sm">
          <span className="mb-1 block text-xs font-medium uppercase text-muted">Cost basis method</span>
          <select
            aria-label="Cost basis method"
            value={costBasisMethod}
            onChange={(e) => setCostBasisMethod(e.target.value as CostBasisMethodValue)}
            className="w-full rounded border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm"
          >
            <option value="FIFO">FIFO</option>
            <option value="LIFO">LIFO</option>
            <option value="AvgCost">AvgCost</option>
          </select>
        </label>
      </div>

      <div className="flex justify-end">
        <button type="submit" disabled={submitting} className="btn-primary">
          {submitting ? "Recording..." : "Submit trade"}
        </button>
      </div>
    </form>
  );
}

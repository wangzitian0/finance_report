/**
 * Normalizers and ViewModels for Frontend UI (#1985).
 *
 * Explicit bifurcation between pure OpenAPI wire contracts (`Schemas["..."]`)
 * and UI view models with calculated/derived fields.
 */

import type { Schemas } from "./api-schema";
import type { JournalLine, MoneyValue } from "./types";

/**
 * UI View Model for bank statement transactions.
 * Extends the wire shape with UI review states, confidence badges, and running balance.
 */
export interface BankStatementTransactionViewModel {
  id: string;
  statement_id?: string | null;
  txn_date: string;
  description: string;
  amount: MoneyValue;
  direction: string;
  reference?: string | null;
  currency?: string | null;
  balance_after?: MoneyValue | null;
  status?: "pending" | "matched" | "unmatched";
  confidence?: "high" | "medium" | "low";
  confidence_tier?: "TRUSTED" | "HIGH" | "MEDIUM" | "LOW";
  confidence_reason?: string | null;
  raw_text?: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Normalizer converting raw AtomicTransactionResponse or BankTransactionSummary wire DTOs
 * into BankStatementTransactionViewModel for UI consumption.
 */
export function toTransactionViewModel(
  raw:
    | Schemas["AtomicTransactionResponse"]
    | Schemas["BankTransactionSummary"],
  overrides?: Partial<BankStatementTransactionViewModel>,
): BankStatementTransactionViewModel {
  const isAtomic = "created_at" in raw;
  const rawConfidence = "confidence_tier" in raw ? raw.confidence_tier : undefined;
  return {
    id: raw.id,
    statement_id: raw.statement_id ?? null,
    txn_date: "txn_date" in raw ? raw.txn_date : "",
    description: raw.description,
    amount: raw.amount,
    direction: raw.direction,
    reference: ("reference" in raw ? raw.reference : null) ?? null,
    currency: ("currency" in raw ? raw.currency : null) ?? null,
    balance_after: overrides?.balance_after ?? null,
    status: overrides?.status ?? "pending",
    confidence: overrides?.confidence,
    confidence_tier:
      overrides?.confidence_tier ??
      (rawConfidence as "TRUSTED" | "HIGH" | "MEDIUM" | "LOW" | undefined),
    confidence_reason: overrides?.confidence_reason ?? null,
    raw_text: overrides?.raw_text ?? null,
    created_at: isAtomic ? (raw as Schemas["AtomicTransactionResponse"]).created_at : new Date().toISOString(),
    updated_at: isAtomic ? (raw as Schemas["AtomicTransactionResponse"]).updated_at : new Date().toISOString(),
    ...overrides,
  };
}

/**
 * UI View Model for journal entries.
 * Accommodates aggregate view presentation fields such as `total_amount`.
 */
export interface JournalEntryViewModel {
  id: string;
  entry_date: string;
  memo: string;
  source_type: string;
  confidence_tier?:
    | "TRUSTED"
    | "HIGH"
    | "MEDIUM"
    | "LOW"
    | "DETERMINISTIC"
    | null;
  status: "draft" | "posted" | "reconciled" | "void" | string;
  lines: JournalLine[];
  created_at: string;
  total_amount?: MoneyValue;
}

/**
 * Normalizer mapping JournalEntryResponse to JournalEntryViewModel with optional computed total.
 */
export function toJournalEntryViewModel(
  entry: Schemas["JournalEntryResponse"],
  total_amount?: MoneyValue,
): JournalEntryViewModel {
  return {
    ...entry,
    lines: (entry.lines ?? []).map((line) => ({
      id: line.id,
      account_id: line.account_id,
      direction: line.direction,
      amount: line.amount,
      currency: line.currency,
      fx_rate: line.fx_rate,
    })),
    total_amount,
  };
}

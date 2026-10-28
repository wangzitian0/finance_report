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
  confidence_tier?: "TRUSTED" | "HIGH" | "MEDIUM" | "LOW" | null;
  confidence_score?: number | null;
  confidence_reason?: string | null;
  proposed_category?: Schemas["TransactionCategory"] | string | null;
  category?: string | null;
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
  const rawLegacyConfidence =
    "confidence" in raw
      ? (raw as { confidence?: "high" | "medium" | "low" }).confidence
      : undefined;
  const rawConfidenceScore =
    "confidence_score" in raw ? raw.confidence_score : undefined;
  const rawProposedCategory =
    "proposed_category" in raw ? raw.proposed_category : undefined;
  const rawCategory =
    "category" in raw
      ? (raw as { category?: string | null }).category
      : undefined;
  const derivedConfidence: "high" | "medium" | "low" | undefined =
    rawConfidence === "HIGH" || rawConfidence === "TRUSTED"
      ? "high"
      : rawConfidence === "MEDIUM"
        ? "medium"
        : rawConfidence === "LOW"
          ? "low"
          : undefined;
  const rawBalanceAfter =
    "balance_after" in raw
      ? (raw as { balance_after?: MoneyValue | null }).balance_after
      : null;
  return {
    id: raw.id,
    statement_id: raw.statement_id ?? null,
    txn_date: "txn_date" in raw ? raw.txn_date : "",
    description: raw.description,
    amount: raw.amount,
    direction: raw.direction,
    reference: ("reference" in raw ? raw.reference : null) ?? null,
    currency: ("currency" in raw ? raw.currency : null) ?? null,
    balance_after: overrides?.balance_after ?? rawBalanceAfter ?? null,
    // The wire has no transaction status. The statement table derives it from the statement
    // state, so the view model does not invent one (#2647: an approved statement showed "pending").
    status: overrides?.status,
    // A row with no tier has no confidence: it is not rated, not low (#2647).
    confidence: overrides?.confidence ?? derivedConfidence ?? rawLegacyConfidence,
    confidence_tier:
      overrides?.confidence_tier ??
      (rawConfidence as "TRUSTED" | "HIGH" | "MEDIUM" | "LOW" | null | undefined) ??
      null,
    confidence_score:
      overrides?.confidence_score ?? rawConfidenceScore ?? null,
    confidence_reason: overrides?.confidence_reason ?? null,
    proposed_category:
      overrides?.proposed_category ?? rawProposedCategory ?? null,
    category:
      overrides?.category ?? rawCategory ?? rawProposedCategory ?? null,
    raw_text: overrides?.raw_text ?? null,
    created_at: isAtomic
      ? (raw as Schemas["AtomicTransactionResponse"]).created_at
      : "txn_date" in raw && raw.txn_date
        ? `${raw.txn_date}T00:00:00Z`
        : "1970-01-01T00:00:00Z",
    updated_at: isAtomic
      ? (raw as Schemas["AtomicTransactionResponse"]).updated_at
      : "txn_date" in raw && raw.txn_date
        ? `${raw.txn_date}T00:00:00Z`
        : "1970-01-01T00:00:00Z",
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
  status: Schemas["JournalEntryStatus"];
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
    lines: entry.lines ?? [],
    total_amount,
  };
}

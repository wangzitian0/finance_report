/**
 * Normalizers and ViewModels for Frontend UI (#1985).
 *
 * Explicit bifurcation between pure OpenAPI wire contracts (`Schemas["..."]`)
 * and UI view models with calculated/derived fields.
 */

import type { Schemas } from "./api-schema";
import type { MoneyValue } from "./types";

type RawTransactionConfidenceTier = "TRUSTED" | "HIGH" | "MEDIUM" | "LOW";

/**
 * UI View Model for bank statement transactions.
 * Derives wire fields from AtomicTransactionResponse and adds UI review states.
 */
export type BankStatementTransactionViewModel = Omit<
  Schemas["AtomicTransactionResponse"],
  "category" | "proposed_category" | "confidence_tier" | "created_at" | "updated_at"
> & {
  category?: string | null;
  proposed_category?: Schemas["TransactionCategory"] | string | null;
  confidence_tier?: RawTransactionConfidenceTier | null;
  status?: "pending" | "matched" | "unmatched";
  confidence?: "high" | "medium" | "low";
  confidence_reason?: string | null;
  raw_text?: string | null;
  created_at?: string;
  updated_at?: string;
};

/**
 * Normalizer converting raw AtomicTransactionResponse or BankTransactionSummary wire DTOs
 * into BankStatementTransactionViewModel for UI consumption.
 */
export function toTransactionViewModel(
  raw: Schemas["AtomicTransactionResponse"] | Schemas["BankTransactionSummary"],
  overrides?: Partial<BankStatementTransactionViewModel>,
): BankStatementTransactionViewModel {
  const fields = raw as Partial<Schemas["AtomicTransactionResponse"]>;
  const rawConfidence = fields.confidence_tier as RawTransactionConfidenceTier | null | undefined;
  const derivedConfidence: "high" | "medium" | "low" | undefined =
    rawConfidence === "HIGH" || rawConfidence === "TRUSTED"
      ? "high"
      : rawConfidence === "MEDIUM"
        ? "medium"
        : rawConfidence === "LOW"
          ? "low"
          : undefined;
  const synthesizedTs = fields.txn_date ? `${fields.txn_date}T00:00:00Z` : undefined;
  return {
    id: raw.id,
    statement_id: raw.statement_id ?? null,
    source_row: overrides?.source_row ?? fields.source_row ?? null,
    txn_date: fields.txn_date ?? "",
    description: raw.description,
    amount: raw.amount,
    direction: raw.direction,
    reference: fields.reference ?? null,
    currency: fields.currency ?? null,
    balance_after: overrides?.balance_after ?? fields.balance_after ?? null,
    // The wire has no transaction status. The statement table derives it from the statement
    // state, so the view model does not invent one (#2647: an approved statement showed "pending").
    status: overrides?.status,
    // A row with no tier has no confidence: it is not rated, not low (#2647).
    confidence: overrides?.confidence ?? derivedConfidence,
    confidence_tier: overrides?.confidence_tier ?? rawConfidence ?? null,
    confidence_score: overrides?.confidence_score ?? fields.confidence_score ?? null,
    confidence_reason: overrides?.confidence_reason ?? null,
    proposed_category: overrides?.proposed_category ?? fields.proposed_category ?? null,
    category: overrides?.category ?? fields.category ?? fields.proposed_category ?? null,
    raw_text: overrides?.raw_text ?? null,
    created_at: fields.created_at ?? synthesizedTs,
    updated_at: fields.updated_at ?? synthesizedTs,
    ...overrides,
  };
}

/**
 * UI View Model for journal entries.
 * Derives wire fields from JournalEntryResponse and adds optional computed total.
 */
export type JournalEntryViewModel = Omit<
  Schemas["JournalEntryResponse"],
  "source_type" | "user_id" | "updated_at" | "decision_authority_state"
> &
  Partial<Pick<Schemas["JournalEntryResponse"], "user_id" | "updated_at" | "decision_authority_state">> & {
    source_type: string;
    total_amount?: MoneyValue;
  };

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

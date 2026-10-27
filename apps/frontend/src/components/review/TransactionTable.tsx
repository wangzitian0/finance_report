"use client";

import { useState } from "react";
import Link from "next/link";
import { formatCurrencyLocale } from "@/lib/audit/money";
import { formatCategoryLabel } from "@/lib/categories";
import { confidenceLabel, statementDisplayTitle } from "@/lib/statusLabels";
import type { BankStatement, BankStatementTransaction, BalanceValidationResult, BrokerageImportResponse, MoneyValue } from "@/lib/types";
import { StatusBadge } from "@/components/ui";
import DetailDialog from "@/components/ui/DetailDialog";
import { RowConfidenceBadge } from "@/components/review/RowConfidenceBadge";

export type Transaction = BankStatementTransaction;

export interface EnvelopeDraft {
  accountId: string;
  currency: string;
  periodStart: string;
  periodEnd: string;
  openingBalance: string;
  closingBalance: string;
  rationale: string;
}

export interface CustodyAccount {
  id: string;
  name: string;
  currency: string;
  type?: string;
  is_active?: boolean;
}

export function BalanceIndicator({ openingBalance, closingBalance, validationResult, currency }: {
  openingBalance: MoneyValue | null; closingBalance: MoneyValue | null; validationResult: BalanceValidationResult | null; currency: string;
}) {
  const openingValid = validationResult?.opening_match ?? false;
  const closingValid = validationResult?.closing_match ?? false;
  const closingKnown = (validationResult?.closing_balance ?? null) !== null;
  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 mb-4">
      <div className="card p-4"><div className="text-xs text-muted mb-1">Opening Balance</div><div className="text-lg font-semibold">{formatCurrencyLocale(openingBalance ?? 0, currency)}</div></div>
      <div className="card p-4"><div className="text-xs text-muted mb-1">Closing Balance</div><div className="text-lg font-semibold">{formatCurrencyLocale(closingBalance ?? 0, currency)}</div></div>
      <div className="card p-4"><div className="text-xs text-muted mb-1">Calculated Closing</div><div className="text-lg font-semibold">{formatCurrencyLocale(validationResult ? validationResult.calculated_closing : 0, currency)}</div></div>
      <div className="card p-4">
        <div className="text-xs text-muted mb-2">Balance Validation</div>
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-3">
            <span className={`text-sm font-medium ${openingValid ? "text-[var(--success)]" : "text-[var(--error)]"}`}>Opening {openingValid ? "Valid" : "Mismatch"}</span>
            <span className="text-xs text-muted">Opening Δ: {validationResult?.opening_delta || "?"}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className={`text-sm font-medium ${!closingKnown ? "text-muted" : closingValid ? "text-[var(--success)]" : "text-[var(--error)]"}`}>Closing {!closingKnown ? "Unknown" : closingValid ? "Valid" : "Mismatch"}</span>
            <span className="text-xs text-muted">Closing Δ: {validationResult?.closing_delta || "?"}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export function ReviewActionBar({ onApprove, onReject, actionLoading, balanceValid, statementStatus = "completed", approvalBlockedReason = null, onResolveConflicts, onReparse, reparsePending = false }: {
  onApprove: () => void; onReject: () => void; actionLoading: boolean; balanceValid: boolean; statementStatus?: string; approvalBlockedReason?: string | null; onResolveConflicts?: () => void; onReparse?: () => void; reparsePending?: boolean;
}) {
  const isParsing = statementStatus === "parsing";
  const blockedByReview = Boolean(approvalBlockedReason);
  const blockedByConflicts = blockedByReview && Boolean(onResolveConflicts);
  const blockedByBalance = !isParsing && !blockedByReview && !balanceValid;
  const isBlocked = isParsing || blockedByReview || blockedByBalance;
  const reason = isParsing ? "Approve is paused — extraction is in progress."
    : blockedByConflicts ? "Approve is paused — we found possible duplicate or transfer-pair transactions. Review them before approving."
    : blockedByReview ? (approvalBlockedReason || "Approve is paused until the required review is complete.")
    : blockedByBalance ? "Approve is paused — this statement's closing balance doesn't match its transactions. Re-parsing usually fixes this." : "";
  return (
    <div className="flex w-full flex-col gap-2 sm:w-auto sm:items-end">
      <div className="grid w-full grid-cols-2 gap-2 sm:flex sm:w-auto sm:items-center">
        <button type="button" onClick={onReject} disabled={actionLoading} className="btn-secondary text-[var(--error)] border-[var(--error)]/30 hover:bg-[var(--error-muted)]">Reject</button>
        <button type="button" onClick={onApprove} disabled={actionLoading || isBlocked} className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed" title={reason}>{actionLoading ? "Processing..." : "Approve"}</button>
      </div>
      {isBlocked && (
        <div role="status" className="flex w-full flex-col gap-2 rounded-md border border-[var(--warning)]/30 bg-[var(--warning-muted)] p-3 text-sm sm:max-w-sm">
          <p className="text-[var(--foreground)]">{reason}</p>
          {blockedByConflicts && onResolveConflicts && <button type="button" onClick={onResolveConflicts} className="btn-secondary btn-sm self-start">Resolve conflicts</button>}
          {blockedByBalance && onReparse && <button type="button" onClick={onReparse} disabled={reparsePending} className="btn-secondary btn-sm self-start disabled:opacity-50">{reparsePending ? "Re-parsing…" : "Re-parse statement"}</button>}
        </div>
      )}
    </div>
  );
}

export function ConflictResolutionDialog({ isOpen, onClose, duplicateCandidates, transferPairCandidates, onResolve, isResolving = false }: {
  isOpen: boolean; onClose: () => void; duplicateCandidates: { id: string; description: string; txn_date: string; amount: MoneyValue }[]; transferPairCandidates: { id: string; description: string; txn_date: string; amount: MoneyValue }[]; onResolve?: (action: "confirm_distinct" | "link_transfer") => void; isResolving?: boolean;
}) {
  return (
    <DetailDialog isOpen={isOpen} onClose={onClose} title="Resolve Conflicts" maxWidth="max-w-2xl">
      {duplicateCandidates.length === 0 && transferPairCandidates.length === 0 ? (
        <div className="text-center py-8 text-muted"><p>No conflicts detected for this statement.</p></div>
      ) : (
        <div className="space-y-6">
          {duplicateCandidates.length > 0 && (
            <div>
              <h3 className="text-sm font-medium mb-2 flex items-center gap-2"><span className="w-2 h-2 bg-[var(--warning)] rounded-full" />Duplicate Candidates</h3>
              <div className="space-y-2">{duplicateCandidates.map((c, i) => (
                <div key={`duplicate-${c.id}-${i}`} className="p-3 border border-[var(--border)] rounded bg-[var(--background-muted)]/30 flex items-center justify-between">
                  <div className="text-sm"><div className="font-medium">{c.description}</div><div className="text-xs text-muted">{c.txn_date} • {c.amount}</div></div>
                  <button type="button" className="btn-primary btn-sm" disabled={isResolving || !onResolve} onClick={() => onResolve?.("confirm_distinct")}>{isResolving ? "Resolving…" : "Resolve"}</button>
                </div>
              ))}</div>
            </div>
          )}
          {transferPairCandidates.length > 0 && (
            <div>
              <h3 className="text-sm font-medium mb-2 flex items-center gap-2"><span className="w-2 h-2 bg-[var(--accent)] rounded-full" />Transfer Pair Candidates</h3>
              <div className="space-y-2">{transferPairCandidates.map((c, i) => (
                <div key={`transfer-${c.id}-${i}`} className="p-3 border border-[var(--border)] rounded bg-[var(--background-muted)]/30 flex items-center justify-between">
                  <div className="text-sm"><div className="font-medium">{c.description}</div><div className="text-xs text-muted">{c.txn_date} • {c.amount}</div></div>
                  <button type="button" className="btn-primary btn-sm" disabled={isResolving || !onResolve} onClick={() => onResolve?.("link_transfer")}>{isResolving ? "Resolving…" : "Link Pair"}</button>
                </div>
              ))}</div>
            </div>
          )}
        </div>
      )}
      <div className="mt-6 flex justify-end border-t border-[var(--border)] pt-4"><button type="button" onClick={onClose} className="btn-secondary">Close</button></div>
    </DetailDialog>
  );
}

export function SourceEnvelopeConfirmation({ requiresEnvelopeConfirmation, requiresOtherSourceReview, sourceMissingFacts, missingFactLabels, envelopeDraft, onDraftChange, custodyAccounts, onConfirm, isPending, reviewedEnvelope, onCreateAccount, isCreatingAccount = false, defaultAccountName = "" }: {
  requiresEnvelopeConfirmation: boolean; requiresOtherSourceReview: boolean; sourceMissingFacts: string[]; missingFactLabels: Record<string, string>; envelopeDraft: EnvelopeDraft; onDraftChange: (u: (p: EnvelopeDraft) => EnvelopeDraft) => void; custodyAccounts: CustodyAccount[]; onConfirm: () => void; isPending: boolean; reviewedEnvelope?: unknown | null; onCreateAccount?: (name: string) => void; isCreatingAccount?: boolean; defaultAccountName?: string;
}) {
  const [newAccountName, setNewAccountName] = useState(defaultAccountName);
  const canCreateAccount = Boolean(onCreateAccount) && custodyAccounts.length === 0;
  const isComplete = Boolean(envelopeDraft.accountId && envelopeDraft.currency && envelopeDraft.periodStart && envelopeDraft.periodEnd && envelopeDraft.openingBalance && envelopeDraft.closingBalance && envelopeDraft.rationale.trim());
  const missingText = sourceMissingFacts.map((f) => missingFactLabels[f] || f).join(", ");
  return (
    <>
      {requiresEnvelopeConfirmation && (
        <section className="mb-4 rounded-lg border border-[var(--warning)]/40 bg-[var(--warning-muted)] p-4" aria-labelledby="source-envelope-heading">
          <div className="mb-3">
            <h2 id="source-envelope-heading" className="font-semibold">{sourceMissingFacts.length ? "Confirm missing source facts" : "Confirm source facts"}</h2>
            <p className="mt-1 text-sm text-muted">{sourceMissingFacts.length ? `This source did not declare ${missingText}. Confirm only facts you can support from the original document or export.` : "This statement needs your confirmation before it can be used. Check the transaction list, account, dates, and balances against the original document. Known source facts must remain unchanged."}</p>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <label className="text-sm font-medium" htmlFor="custody-account">Custody account
              <select id="custody-account" value={envelopeDraft.accountId} onChange={(e) => onDraftChange((c) => ({ ...c, accountId: e.target.value }))} className="input mt-1 w-full">
                <option value="">Select an asset account</option>
                {custodyAccounts.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.currency})</option>)}
              </select>
            </label>
            {canCreateAccount && (
              <div className="rounded-md border border-[var(--border)] p-2 text-sm md:col-span-2">
                <span className="block text-xs text-muted">You have no asset account yet. Create one for this statement{envelopeDraft.currency ? ` in ${envelopeDraft.currency}` : ""}.</span>
                <span className="mt-2 flex gap-2">
                  <input id="new-custody-account-name" aria-label="New account name" value={newAccountName} onChange={(e) => setNewAccountName(e.target.value)} className="input w-full" placeholder="e.g., DBS Savings" />
                  <button type="button" onClick={() => onCreateAccount?.(newAccountName.trim())} disabled={isCreatingAccount || !newAccountName.trim() || !envelopeDraft.currency} className="btn-secondary whitespace-nowrap disabled:cursor-not-allowed disabled:opacity-50">{isCreatingAccount ? "Creating..." : "Create account"}</button>
                </span>
              </div>
            )}
            <label className="text-sm font-medium" htmlFor="statement-currency">Statement currency<input id="statement-currency" value={envelopeDraft.currency} onChange={(e) => onDraftChange((c) => ({ ...c, currency: e.target.value.toUpperCase() }))} className="input mt-1 w-full" maxLength={3} placeholder="SGD" /></label>
            <label className="text-sm font-medium" htmlFor="period-start">Period start<input id="period-start" type="date" value={envelopeDraft.periodStart} onChange={(e) => onDraftChange((c) => ({ ...c, periodStart: e.target.value }))} className="input mt-1 w-full" /></label>
            <label className="text-sm font-medium" htmlFor="period-end">Period end<input id="period-end" type="date" value={envelopeDraft.periodEnd} onChange={(e) => onDraftChange((c) => ({ ...c, periodEnd: e.target.value }))} className="input mt-1 w-full" /></label>
            <label className="text-sm font-medium" htmlFor="opening-balance">Opening balance<input id="opening-balance" inputMode="decimal" value={envelopeDraft.openingBalance} onChange={(e) => onDraftChange((c) => ({ ...c, openingBalance: e.target.value }))} className="input mt-1 w-full" /></label>
            <label className="text-sm font-medium" htmlFor="closing-balance">Closing balance<input id="closing-balance" inputMode="decimal" value={envelopeDraft.closingBalance} onChange={(e) => onDraftChange((c) => ({ ...c, closingBalance: e.target.value }))} className="input mt-1 w-full" /></label>
          </div>
          <label className="mt-3 block text-sm font-medium" htmlFor="envelope-rationale">Why are these facts confirmed?<textarea id="envelope-rationale" value={envelopeDraft.rationale} onChange={(e) => onDraftChange((c) => ({ ...c, rationale: e.target.value }))} className="input mt-1 min-h-20 w-full" placeholder="State the page, export header, or other source evidence used." /></label>
          <button type="button" onClick={onConfirm} disabled={isPending || !isComplete} className="btn-primary mt-3 disabled:cursor-not-allowed disabled:opacity-50">{isPending ? "Confirming..." : "Confirm source envelope"}</button>
        </section>
      )}
      {requiresOtherSourceReview && (
        <section className="mb-4 rounded-lg border border-[var(--warning)]/40 bg-[var(--warning-muted)] p-4" aria-labelledby="source-review-required-heading">
          <h2 id="source-review-required-heading" className="font-semibold">Source review required</h2>
          <p className="mt-1 text-sm text-muted">{missingText} cannot be confirmed by a cash statement envelope. Re-parse the source or use the review path that owns those facts.</p>
        </section>
      )}
      {Boolean(reviewedEnvelope) && <p className="mb-4 rounded-md border border-[var(--success)]/30 bg-[var(--success-muted)] p-3 text-sm">Source envelope confirmed and anchored to the current extraction result.</p>}
    </>
  );
}

const CONFIDENCE_TIER_RANK: Record<string, number> = { LOW: 0, MEDIUM: 1, HIGH: 2, TRUSTED: 3, DETERMINISTIC: 3 };
const CONFIDENCE_RANK: Record<string, number> = { low: 0, medium: 1, high: 2 };

/**
 * The confidence rank of a row: 0 is low. The tier wins over the coarse confidence, as the badge
 * shows. Null is a row with no known tier and no confidence: it is not rated, not low.
 */
export function confidenceRank(txn: Pick<Transaction, "confidence_tier" | "confidence">): number | null {
  if (txn.confidence_tier && txn.confidence_tier in CONFIDENCE_TIER_RANK) return CONFIDENCE_TIER_RANK[txn.confidence_tier];
  if (txn.confidence && txn.confidence in CONFIDENCE_RANK) return CONFIDENCE_RANK[txn.confidence];
  return null;
}

/**
 * A row of the statement table with its 1-based position in the API order. The API sends the rows
 * in date order (transaction date, then creation time), not in the line order of the source file.
 */
export interface OrderedStatementRow<T> {
  txn: T;
  datePosition: number;
  /** True for a low-confidence row: it is above the other rows. */
  pinned: boolean;
}

/**
 * The low-confidence rows on top, in date order, then every other row in date order (#2647).
 * Only a low row moves. An unrated row is not low.
 */
export function pinLowConfidenceRows<T extends Pick<Transaction, "confidence_tier" | "confidence">>(
  rows: readonly T[],
): OrderedStatementRow<T>[] {
  const numbered = rows.map((txn, index) => ({ txn, datePosition: index + 1, pinned: confidenceRank(txn) === 0 }));
  return [...numbered.filter((row) => row.pinned), ...numbered.filter((row) => !row.pinned)];
}

/**
 * The date-order position of a pinned row ("Row 6 of 6 by date"): the row no longer sits at that
 * position. It is not the line number of the source file.
 */
function DateRowNumber({ row, total }: { row: OrderedStatementRow<Transaction>; total: number }) {
  if (!row.pinned) return null;
  return <span data-testid="date-row-number" className="text-xs text-muted">{`Row ${row.datePosition} of ${total} by date`}</span>;
}

export function TransactionTable({ transactions, currency, onSelectTransaction, statementStatus }: { transactions: Transaction[]; currency: string; onSelectTransaction?: (txn: Transaction) => void; statementStatus?: string }) {
  const rows = pinLowConfidenceRows(transactions ?? []);
  const lowCount = rows.filter((row) => row.pinned).length;
  const renderStatus = (txn: Transaction) => <StatusBadge status={statementStatus === "approved" ? "matched" : (txn.status ?? "pending")} variants={{ pending: "warning", matched: "success", unmatched: "error" }} />;
  const renderConf = (txn: Transaction) => <RowConfidenceBadge txn={txn} />;
  return (
    <div className="card flex h-full min-h-0 min-w-0 max-w-full flex-col overflow-hidden">
      <div className="card-header flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h3 className="text-sm font-medium">Transactions</h3>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {lowCount > 0 && <span data-testid="low-confidence-count" className="badge badge-error">{`${lowCount} low confidence · shown first`}</span>}
          {/* The other rows keep the API order: date order (#2647). */}
          <span className="text-muted">{rows.length > 0 ? `${rows.length} total · by date` : "0 total"}</span>
        </div>
      </div>
      {/* The mobile list grows with the page: one page scroll, no inner scroll box (#2647). */}
      <div data-testid="stage1-mobile-transaction-list" className="min-w-0 divide-y divide-[var(--border)] md:hidden">
        {rows.map((row) => {
          const { txn } = row;
          const cat = formatCategoryLabel(txn.category ?? txn.proposed_category);
          return (
            <article key={txn.id} data-testid={`stage1-mobile-transaction-card-${txn.id}`} className="min-w-0 space-y-4 p-4">
              <div className="flex min-w-0 items-start justify-between gap-3">
                <div className="min-w-0 flex-1"><p className="text-xs font-medium uppercase text-muted">Transaction</p><p className="mt-1 break-words font-medium">{txn.description}</p>{cat && <span className="mt-1 inline-block rounded-full bg-[var(--background-muted)] px-2 py-0.5 text-xs font-medium text-[var(--foreground)]">{cat}</span>}<div><DateRowNumber row={row} total={rows.length} /></div></div>
                <div className="flex-shrink-0">{renderConf(txn)}</div>
              </div>
              <div className="grid grid-cols-1 gap-3 text-sm">
                <div><span className="block text-xs font-medium uppercase text-muted">Date</span><p>{txn.txn_date}</p></div>
                <div><span className="block text-xs font-medium uppercase text-muted">Direction</span><p>{txn.direction}</p></div>
                <p className={`min-w-0 break-words text-right text-sm font-semibold ${txn.direction === "IN" ? "text-[var(--success)]" : "text-[var(--error)]"}`}>{txn.direction === "IN" ? "+" : "-"}{formatCurrencyLocale(txn.amount, txn.currency || currency)}</p>
              </div>
              {onSelectTransaction && <div className="pt-2 border-t border-[var(--border)]/50"><button type="button" onClick={() => onSelectTransaction(txn)} className="btn-secondary btn-sm w-full text-xs">Review / Fix</button></div>}
            </article>
          );
        })}
      </div>
      <div data-testid="stage1-desktop-transaction-region" className="hidden min-h-0 flex-1 overflow-y-auto overflow-x-hidden md:block">
        <table className="table-fixed border-collapse text-sm" style={{ width: onSelectTransaction ? "calc(100% - 16px)" : "calc(100% - 4px)" }}>
          <thead className="sticky top-0 bg-[var(--background)]"><tr className="border-b border-[var(--border)]"><th className="text-left px-4 py-2 font-medium w-24">Date</th><th className="text-left px-4 py-2 font-medium">Description</th><th className="text-right px-4 py-2 font-medium w-32">Amount</th><th className="text-center px-4 py-2 font-medium w-24">Confidence</th>{onSelectTransaction && <th className="text-right px-2 py-2 font-medium w-16">Action</th>}</tr></thead>
          <tbody className="divide-y divide-[var(--border)]">
            {rows.map((row) => {
              const { txn } = row;
              const cat = formatCategoryLabel(txn.category ?? txn.proposed_category);
              return (
                <tr key={txn.id} className="hover:bg-[var(--background-muted)]/50 group">
                  <td className="px-4 py-2 whitespace-nowrap">{txn.txn_date}</td>
                  <td className="px-4 py-2"><div className="break-words" title={txn.description}>{txn.description}</div><div className="mt-0.5 flex flex-wrap items-center gap-1">{cat && <span className="inline-block rounded-full bg-[var(--background-muted)] px-2 py-0.5 text-xs font-medium text-[var(--foreground)]">{cat}</span>}{statementStatus && renderStatus(txn)}<DateRowNumber row={row} total={rows.length} /></div></td>
                  <td className={`px-4 py-2 text-right font-medium whitespace-nowrap ${txn.direction === "IN" ? "text-[var(--success)]" : "text-[var(--error)]"}`}>{txn.direction === "IN" ? "+" : "-"}{formatCurrencyLocale(txn.amount, txn.currency || currency)}</td>
                  <td className="px-4 py-2 text-center">{renderConf(txn)}</td>
                  {onSelectTransaction && <td className="px-2 py-2 text-right whitespace-nowrap"><button type="button" onClick={() => onSelectTransaction(txn)} className="rounded px-2 py-1 text-xs font-medium text-[var(--accent)] hover:bg-[var(--accent)]/10">Review</button></td>}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function StatementHeader({ statement, canImport, canRetry, canDelete = true, importLoading, retryLoading, deleteLoading = false, onBrokerageImport, onRetry, onDelete, formatCode, formatPeriod }: {
  statement: BankStatement; canImport: boolean; canRetry: boolean; canDelete?: boolean; importLoading: boolean; retryLoading: boolean; deleteLoading?: boolean; onBrokerageImport: () => void; onRetry: () => void; onDelete?: () => void; formatCode: (c?: string | null) => string; formatPeriod: (s?: string | null, e?: string | null, missing?: string) => string;
}) {
  return (
    <div className="page-header flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
      <div className="flex-1 min-w-0 w-full">
        <div className="flex flex-wrap items-center gap-3 mb-2">
          <h1 className="page-title truncate">{statementDisplayTitle(statement)}</h1>
          <StatusBadge status={statement.status} variants={{ approved: "success", rejected: "error", parsed: "warning" }} />
          {statement.original_filename && <span data-testid="statement-original-filename-badge" className="inline-flex items-center rounded-md border border-[var(--border)] bg-[var(--background-muted)] px-2.5 py-0.5 text-xs font-medium text-[var(--foreground-muted)]">Source file: {statement.original_filename}</span>}
        </div>
        <p className="page-description">{statement.institution} • {formatCode(statement.currency)} • {formatPeriod(statement.period_start, statement.period_end, statement.status === "parsing" ? "Parsing..." : undefined)}{statement.confidence_score != null && <> • Confidence {statement.confidence_score}% ({confidenceLabel(statement.confidence_score)})</>}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {canImport && <button type="button" onClick={onBrokerageImport} disabled={importLoading} className="btn-secondary flex items-center gap-2" aria-label="Import brokerage positions to portfolio">{importLoading ? "Importing..." : "Import to Portfolio"}</button>}
        {canRetry && <button type="button" onClick={onRetry} disabled={retryLoading} className="btn-secondary flex items-center gap-2">Retry Parse</button>}
        {canDelete && onDelete && <button type="button" onClick={onDelete} disabled={deleteLoading} className="btn-secondary text-[var(--error)] border-[var(--error)]/30 hover:bg-[var(--error-muted)] flex items-center gap-2" aria-label="Delete statement">Delete</button>}
      </div>
    </div>
  );
}

export function BrokerageImportResultBanner({ importResult }: { importResult: BrokerageImportResponse }) {
  return (
    <div className="mb-4 p-4 border border-[var(--success)]/30 bg-[var(--success-muted)] rounded-lg" data-testid="import-result-banner">
      <div className="font-medium text-[var(--success)] mb-2">Brokerage positions imported successfully</div>
      <div className="text-sm space-y-0.5 mb-3">
        <div><span className="text-muted">Broker:</span> <span className="font-medium">{importResult.broker}</span></div>
        <div><span className="text-muted">Positions parsed:</span> <span className="font-medium">{importResult.parsed_positions}</span></div>
        <div><span className="text-muted">New holdings created:</span> <span className="font-medium">{importResult.created_atomic_positions}</span></div>
        <div><span className="text-muted">Holdings reconciled:</span> <span className="font-medium">{importResult.reconcile_created + importResult.reconcile_updated}</span></div>
        {importResult.skipped > 0 && <div><span className="text-muted">Skipped:</span> <span className="font-medium">{importResult.skipped}</span></div>}
      </div>
      <Link href="/portfolio" className="btn-secondary text-sm" aria-label="View portfolio after import">View Portfolio →</Link>
    </div>
  );
}

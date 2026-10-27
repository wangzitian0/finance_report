"use client";

import { useEffect, useState } from "react";
import { useForm, useFieldArray } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import DetailDialog from "@/components/ui/DetailDialog";
import { apiOperation } from "@/lib/api-client";
import { formatAmount, isAmountZero, parseAmount, sumAmounts } from "@/lib/audit/money";
import { Account } from "@/lib/types";

interface JournalEntryFormProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

const journalLineSchema = z.object({
  account_id: z.string().min(1, "Account is required"),
  direction: z.enum(["DEBIT", "CREDIT"]),
  amount: z.string().min(1, "Amount is required"),
  currency: z.string(),
  fx_rate: z.string().optional(),
});

const BASE_CURRENCY = "SGD";

function lineBaseAmount(line: z.infer<typeof journalLineSchema>) {
  const currency = line.currency.trim().toUpperCase();
  if (!line.amount) return parseAmount(0);
  const amount = parseAmount(line.amount);
  if (currency === BASE_CURRENCY) return amount;
  if (!line.fx_rate) return null;
  const fxRate = parseAmount(line.fx_rate);
  if (fxRate.lessThanOrEqualTo(0)) return null;
  return amount.times(fxRate);
}

const journalEntrySchema = z
  .object({
    entry_date: z.string().min(1, "Date is required"),
    memo: z.string().min(1, "Memo is required").trim(),
    rationale: z.string().min(1, "Attestation is required").trim(),
    lines: z.array(journalLineSchema).min(2, "At least 2 lines are required"),
  })
  .refine(
    (data) => {
      const baseLines = data.lines.map(lineBaseAmount);
      if (baseLines.some((amount) => amount === null)) return false;
      const sumByDir = (dir: "DEBIT" | "CREDIT") =>
        sumAmounts(
          data.lines
            .map((line, idx) => ({ line, amount: baseLines[idx] }))
            .filter(({ line, amount }) => line.direction === dir && amount !== null)
            .map(({ amount }) => amount!),
        );
      return isAmountZero(sumByDir("DEBIT").minus(sumByDir("CREDIT")), 0.01);
    },
    { message: "Entry must be balanced in SGD base currency and non-SGD lines require FX rates", path: ["lines"] },
  );

type JournalEntryFormValues = z.infer<typeof journalEntrySchema>;

export default function JournalEntryForm({ isOpen, onClose, onSuccess }: JournalEntryFormProps) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [postImmediately, setPostImmediately] = useState(false);

  const {
    register,
    handleSubmit,
    control,
    watch,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<JournalEntryFormValues>({
    resolver: zodResolver(journalEntrySchema),
    defaultValues: {
      entry_date: new Date().toISOString().split("T")[0],
      memo: "",
      rationale: "Recorded by account owner.",
      lines: [
        { account_id: "", direction: "DEBIT", amount: "", currency: "SGD" },
        { account_id: "", direction: "CREDIT", amount: "", currency: "SGD" },
      ],
    },
  });

  const { fields, append, remove } = useFieldArray({ control, name: "lines" });
  const lines = watch("lines");

  useEffect(() => {
    if (isOpen) {
      apiOperation("list_accounts_accounts_get")
        .then((data) => setAccounts(data.items))
        .catch(() => setAccounts([]));
    }
  }, [isOpen]);

  const baseLines = lines.map(lineBaseAmount);
  const hasMissingFxRate = baseLines.some((amount) => amount === null);
  const sumByDir = (dir: "DEBIT" | "CREDIT") =>
    sumAmounts(
      lines
        .map((line, idx) => ({ line, amount: baseLines[idx] }))
        .filter(({ line, amount }) => line.direction === dir && amount !== null)
        .map(({ amount }) => amount!),
    );
  const totalDebits = sumByDir("DEBIT");
  const totalCredits = sumByDir("CREDIT");
  const isBalanced = isAmountZero(totalDebits.minus(totalCredits), 0.01);

  const onSubmit = async (data: JournalEntryFormValues) => {
    setError(null);
    try {
      const createdEntry = await apiOperation("create_entry_journal_entries_post", {
        body: {
          entry_date: data.entry_date,
          memo: data.memo,
          rationale: data.rationale,
          lines: data.lines.map((l) => ({
            account_id: l.account_id,
            direction: l.direction,
            amount: formatAmount(l.amount, 2),
            currency: l.currency.trim().toUpperCase(),
            fx_rate: l.currency.trim().toUpperCase() === BASE_CURRENCY || !l.fx_rate ? undefined : formatAmount(l.fx_rate, 6),
          })),
        },
      });

      if (postImmediately) {
        await apiOperation("post_entry_journal_entries__entry_id__postings_post", { path: { entry_id: createdEntry.id } });
      }

      reset({
        entry_date: new Date().toISOString().slice(0, 10),
        memo: "",
        rationale: "Recorded by account owner.",
        lines: [
          { account_id: "", direction: "DEBIT", amount: "", currency: "SGD" },
          { account_id: "", direction: "CREDIT", amount: "", currency: "SGD" },
        ],
      });
      onSuccess();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create entry");
    }
  };

  if (!isOpen) return null;

  return (
    <DetailDialog isOpen onClose={onClose} title="New Journal Entry" maxWidth="max-w-2xl">
      <p className="mb-4 text-sm text-muted">Create a balanced double-entry transaction</p>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium mb-1.5">Date *</label>
            <input type="date" {...register("entry_date")} className="input" />
            {errors.entry_date && <p className="text-sm text-[var(--error)] mt-1">{errors.entry_date.message}</p>}
          </div>
          <div>
            <label className="block text-sm font-medium mb-1.5">Memo *</label>
            <input type="text" {...register("memo")} placeholder="Description" className="input" />
            {errors.memo && <p className="text-sm text-[var(--error)] mt-1">{errors.memo.message}</p>}
          </div>
          <div>
            <label className="block text-sm font-medium mb-1.5">Attestation *</label>
            <input type="text" {...register("rationale")} placeholder="Why this entry is correct" className="input" />
            {errors.rationale && <p className="text-sm text-[var(--error)] mt-1">{errors.rationale.message}</p>}
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between mb-3">
            <label className="text-sm font-medium">Journal Lines</label>
            <button
              type="button"
              onClick={() => append({ account_id: "", direction: "DEBIT", amount: "", currency: "SGD" })}
              className="text-sm text-[var(--accent)] hover:underline"
            >
              + Add Line
            </button>
          </div>
          <div className="space-y-2">
            {fields.map((field, index) => (
              <div key={field.id} className="grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,1fr)_96px_112px_88px_112px_auto] md:items-center">
                <select {...register(`lines.${index}.account_id`)} className="input flex-1 text-sm" aria-label={`Line ${index + 1} account`}>
                  <option value="">Select Account</option>
                  {accounts.map((acc) => (
                    <option key={acc.id} value={acc.id}>{acc.code ? `${acc.code} - ` : ""}{acc.name}</option>
                  ))}
                </select>
                <select
                  {...register(`lines.${index}.direction`)}
                  className={`input w-24 text-sm ${lines[index]?.direction === "DEBIT" ? "text-[var(--info)]" : "text-[var(--success)]"}`}
                  aria-label={`Line ${index + 1} direction`}
                >
                  <option value="DEBIT">Debit</option>
                  <option value="CREDIT">Credit</option>
                </select>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  {...register(`lines.${index}.amount`)}
                  placeholder="0.00"
                  className="input text-sm text-right"
                  aria-label={`Line ${index + 1} amount`}
                />
                <input
                  type="text"
                  maxLength={3}
                  {...register(`lines.${index}.currency`)}
                  placeholder="SGD"
                  className="input text-sm uppercase"
                  aria-label={`Line ${index + 1} currency`}
                />
                <input
                  type="number"
                  step="0.000001"
                  min="0"
                  {...register(`lines.${index}.fx_rate`)}
                  placeholder="FX rate"
                  disabled={(lines[index]?.currency || BASE_CURRENCY).trim().toUpperCase() === BASE_CURRENCY}
                  className="input text-sm text-right disabled:opacity-40"
                  aria-label={`Line ${index + 1} FX rate`}
                />
                {fields.length > 2 && (
                  <button
                    type="button"
                    onClick={() => remove(index)}
                    className="btn-ghost p-2 text-muted hover:text-[var(--error)]"
                    aria-label={`Remove line ${index + 1}`}
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                )}
              </div>
            ))}
          </div>
          {errors.lines && "message" in errors.lines && <p className="text-sm text-[var(--error)] mt-1">{errors.lines.message}</p>}
        </div>

        <div
          className={`p-3 rounded-md flex items-center justify-between ${
            isBalanced ? "bg-[var(--success-muted)] border border-[var(--success)]/30" : "bg-[var(--error-muted)] border border-[var(--error)]/30"
          }`}
        >
          <div className="flex gap-6 text-sm">
            <div><span className="text-muted">Debits:</span> <span className="font-medium">{formatAmount(totalDebits, 2)}</span></div>
            <div><span className="text-muted">Credits:</span> <span className="font-medium">{formatAmount(totalCredits, 2)}</span></div>
          </div>
          <span className={`text-sm font-medium ${isBalanced ? "text-[var(--success)]" : "text-[var(--error)]"}`}>
            {isBalanced && !hasMissingFxRate ? "✓ Balanced in SGD" : "⚠ Unbalanced or missing FX"}
          </span>
        </div>

        {error && <div className="alert-error">{error}</div>}

        <div className="flex items-center gap-2 py-2">
          <input
            type="checkbox"
            id="postImmediately"
            checked={postImmediately}
            onChange={(e) => setPostImmediately(e.target.checked)}
            className="rounded border-[var(--border)] text-[var(--accent)] focus:ring-[var(--accent)]"
          />
          <label htmlFor="postImmediately" className="text-sm cursor-pointer select-none">Post transaction immediately</label>
        </div>

        <div className="flex gap-3 pt-2">
          <button type="button" onClick={onClose} className="btn-secondary flex-1">Cancel</button>
          <button type="submit" disabled={isSubmitting || !isBalanced || hasMissingFxRate} className="btn-primary flex-1">
            {isSubmitting ? "Processing..." : postImmediately ? "Create & Post" : "Create Draft"}
          </button>
        </div>
      </form>
    </DetailDialog>
  );
}

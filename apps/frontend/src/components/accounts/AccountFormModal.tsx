"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { DetailDialog, Sheet } from "@/components/ui/Overlay";
import { apiOperation } from "@/lib/api-client";
import { formatCurrencyLocale } from "@/lib/audit/money";
import { Account } from "@/lib/types";

interface AccountFormModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (account: Account) => void;
  initialType?: Account["type"];
  editAccount?: Account | null;
}

const ACCOUNT_TYPES = ["ASSET", "LIABILITY", "EQUITY", "INCOME", "EXPENSE"] as const;
const CURRENCIES = ["SGD", "USD", "EUR", "GBP", "JPY", "CNY", "HKD"] as const;

const createAccountSchema = z.object({
  name: z.string().min(1, "Account name is required").trim(),
  code: z.string().trim().optional(),
  type: z.enum(ACCOUNT_TYPES),
  currency: z.enum(CURRENCIES),
  description: z.string().trim().optional(),
});

const editAccountSchema = z.object({
  name: z.string().min(1, "Account name is required").trim(),
  code: z.string().trim().optional(),
  is_active: z.boolean(),
});

type CreateAccountForm = z.infer<typeof createAccountSchema>;
type EditAccountForm = z.infer<typeof editAccountSchema>;

export default function AccountFormModal(props: AccountFormModalProps) {
  if (!props.isOpen) return null;
  return <AccountFormContent key={props.editAccount?.id ?? "create"} {...props} />;
}

function AccountFormContent({ onClose, onSuccess, editAccount, initialType = "ASSET" }: AccountFormModalProps) {
  const [error, setError] = useState<string | null>(null);
  const isEditing = !!editAccount;

  const createForm = useForm<CreateAccountForm>({
    resolver: zodResolver(createAccountSchema),
    defaultValues: { name: "", code: "", type: initialType, currency: "SGD", description: "" },
  });

  const editForm = useForm<EditAccountForm>({
    resolver: zodResolver(editAccountSchema),
    defaultValues: { name: editAccount?.name ?? "", code: editAccount?.code ?? "", is_active: editAccount?.is_active ?? true },
  });

  const handleCreateSubmit = async (data: CreateAccountForm) => {
    setError(null);
    try {
      const account = await apiOperation("create_account_accounts_post", {
        body: { name: data.name, code: data.code || null, type: data.type, currency: data.currency, description: data.description || null },
      });
      onSuccess(account);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create account");
    }
  };

  const handleEditSubmit = async (data: EditAccountForm) => {
    if (!editAccount) return;
    setError(null);
    try {
      const account = await apiOperation("update_account_accounts__account_id__put", {
        path: { account_id: editAccount.id },
        body: { name: data.name, code: data.code || null, is_active: data.is_active },
      });
      onSuccess(account);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update account");
    }
  };

  return (
    <DetailDialog isOpen onClose={onClose} title={isEditing ? "Edit Account" : "New Account"} maxWidth="max-w-md">
      {isEditing ? (
        <form onSubmit={editForm.handleSubmit(handleEditSubmit)} className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1.5">Account Name *</label>
            <input type="text" {...editForm.register("name")} placeholder="e.g., Cash on Hand" className="input" />
            {editForm.formState.errors.name && <p className="text-sm text-[var(--error)] mt-1">{editForm.formState.errors.name.message}</p>}
          </div>
          <div>
            <label className="block text-sm font-medium mb-1.5">Account Code</label>
            <input type="text" {...editForm.register("code")} placeholder="e.g., 1000" className="input" />
            {editForm.formState.errors.code && <p className="text-sm text-[var(--error)] mt-1">{editForm.formState.errors.code.message}</p>}
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" {...editForm.register("is_active")} className="w-4 h-4 rounded border-[var(--border)] bg-[var(--background)] text-[var(--accent)] focus:ring-[var(--accent)]" />
            <span className="text-sm">Active</span>
          </label>
          {error && <div className="alert-error">{error}</div>}
          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose} className="btn-secondary flex-1">Cancel</button>
            <button type="submit" disabled={editForm.formState.isSubmitting} className="btn-primary flex-1">
              {editForm.formState.isSubmitting ? "Saving..." : "Save Changes"}
            </button>
          </div>
        </form>
      ) : (
        <form onSubmit={createForm.handleSubmit(handleCreateSubmit)} className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1.5">Account Name *</label>
            <input type="text" {...createForm.register("name")} placeholder="e.g., Cash on Hand" className="input" />
            {createForm.formState.errors.name && <p className="text-sm text-[var(--error)] mt-1">{createForm.formState.errors.name.message}</p>}
          </div>
          <div>
            <label className="block text-sm font-medium mb-1.5">Account Code</label>
            <input type="text" {...createForm.register("code")} placeholder="e.g., 1000" className="input" />
            {createForm.formState.errors.code && <p className="text-sm text-[var(--error)] mt-1">{createForm.formState.errors.code.message}</p>}
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="new-account-type" className="block text-sm font-medium mb-1.5">Type *</label>
              <select id="new-account-type" {...createForm.register("type")} className="input">
                {ACCOUNT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              {createForm.formState.errors.type && <p className="text-sm text-[var(--error)] mt-1">{createForm.formState.errors.type.message}</p>}
            </div>
            <div>
              <label htmlFor="new-account-currency" className="block text-sm font-medium mb-1.5">Currency *</label>
              <select id="new-account-currency" {...createForm.register("currency")} className="input">
                {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              {createForm.formState.errors.currency && <p className="text-sm text-[var(--error)] mt-1">{createForm.formState.errors.currency.message}</p>}
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1.5">Description</label>
            <textarea {...createForm.register("description")} placeholder="Optional description..." rows={2} className="input resize-none" />
            {createForm.formState.errors.description && <p className="text-sm text-[var(--error)] mt-1">{createForm.formState.errors.description.message}</p>}
          </div>
          {error && <div className="alert-error">{error}</div>}
          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose} className="btn-secondary flex-1">Cancel</button>
            <button type="submit" disabled={createForm.formState.isSubmitting} className="btn-primary flex-1">
              {createForm.formState.isSubmitting ? "Saving..." : "Create Account"}
            </button>
          </div>
        </form>
      )}
    </DetailDialog>
  );
}

export function AccountDetailsSidebar({
  account,
  isOpen,
  onClose,
}: {
  account: Account | null;
  isOpen: boolean;
  onClose: () => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["account-transactions", account?.id],
    queryFn: () =>
      account
        ? apiOperation("list_journal_entries_journal_entries_get", { query: { limit: 50 } })
        : Promise.resolve({ items: [], total: 0 }),
    enabled: !!account && isOpen,
  });

  if (!account) return null;

  const entries = (data?.items ?? [])
    .filter((e) => e.lines.some((l) => l.account_id === account.id))
    .slice(0, 10);

  return (
    <Sheet isOpen={isOpen} onClose={onClose} title="Account Details">
      <div className="space-y-8">
        <div className="space-y-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <h3 className="text-xl font-bold text-[var(--foreground)]">{account.name}</h3>
              <span className="badge badge-primary">{account.type}</span>
            </div>
            {account.code && <p className="text-sm font-mono text-muted">{account.code}</p>}
          </div>
          <div className="grid grid-cols-2 gap-4 pt-2">
            <div>
              <p className="text-xs text-muted mb-1">Currency</p>
              <p className="font-medium">{account.currency}</p>
            </div>
            <div>
              <p className="text-xs text-muted mb-1">Status</p>
              <span className={`badge ${account.is_active ? "badge-success" : "badge-muted"}`}>
                {account.is_active ? "Active" : "Inactive"}
              </span>
            </div>
            <div className="col-span-2">
              <p className="text-xs text-muted mb-1">Current Balance</p>
              <p className="text-2xl font-bold text-[var(--foreground)]">
                {formatCurrencyLocale(account.balance ?? 0, account.currency)}
              </p>
            </div>
          </div>
          {account.description && (
            <div>
              <p className="text-xs text-muted mb-1">Description</p>
              <p className="text-sm">{account.description}</p>
            </div>
          )}
        </div>
        <div className="space-y-4">
          <h4 className="font-semibold border-b border-[var(--border)] pb-2">Recent Transactions</h4>
          {isLoading ? (
            <div className="flex justify-center py-8">
              <div className="w-6 h-6 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
            </div>
          ) : entries.length === 0 ? (
            <div className="text-center py-8 text-sm text-muted bg-[var(--background-muted)]/30 rounded-lg border border-dashed border-[var(--border)]">
              No recent transactions found
            </div>
          ) : (
            <div className="space-y-3">
              {entries.map((entry) =>
                entry.lines
                  .filter((l) => l.account_id === account.id)
                  .map((line, idx) => (
                    <div key={`${entry.id}-${idx}`} className="p-3 rounded-lg border border-[var(--border)] hover:bg-[var(--background-muted)]/50 transition-colors">
                      <div className="flex justify-between items-start gap-4 mb-1">
                        <p className="text-sm font-medium truncate flex-1">{entry.memo}</p>
                        <p className={`text-sm font-bold ${line.direction === "DEBIT" ? "text-[var(--success)]" : "text-[var(--error)]"}`}>
                          {line.direction === "DEBIT" ? "+" : "-"}
                          {formatCurrencyLocale(line.amount, line.currency)}
                        </p>
                      </div>
                      <div className="flex justify-between items-center text-[10px] text-muted">
                        <span>{new Date(entry.entry_date).toLocaleDateString()}</span>
                        <span className="uppercase">{line.direction}</span>
                      </div>
                    </div>
                  )),
              )}
            </div>
          )}
        </div>
      </div>
    </Sheet>
  );
}

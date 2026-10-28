"use client";

import { useToast } from "@/components/ui/Toast";
import { apiOperation } from "@/lib/api-client";
import { useSettingsForm } from "@/hooks/useSettingsForm";
import Link from "next/link";
import type {
  UserAiSettings,
  UserAiSettingsUpdate,
  LlmModelResponse,
  LlmProviderResponse,
  LlmReasoningEffort,
  LlmScene,
  LlmSceneBindingItem,
} from "@/lib/types";
import { NEEDS_YOU_HREF } from "@/lib/attentionNavigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ProviderForm } from "@/components/llm/FirstRunModal";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Scale, Trash2 } from "lucide-react";
import AccountFormModal, { AccountDetailsSidebar } from "@/components/accounts/AccountFormModal";
import { FilterTabs } from "@/components/ui/FilterTabs";
import OpeningBalanceModal from "@/components/accounts/OpeningBalanceModal";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import { Alert, Badge, Button, EmptyState, IconButton, LoadingState, PageHeader } from "@/components/ui";
import { formatCurrencyLocale } from "@/lib/audit/money";
import { formatAccountCodeBadge } from "@/lib/statusLabels";
import { Account } from "@/lib/types";

export function GeneralSettingsPanel() {
  const { showToast } = useToast();
  const { draft, setDraft, loading, submitting, error, isDirty, submit, reset } = useSettingsForm<string>({
    load: async () => (await apiOperation("get_base_currency_app_config_base_currency_get")).base_currency,
    save: async (next) => (await apiOperation("update_base_currency_app_config_base_currency_put", { body: { base_currency: next } })).base_currency,
    loadErrorMessage: "Failed to load base currency",
    saveErrorMessage: "Failed to save base currency",
  });

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const updated = await submit();
    if (updated !== null) showToast("Base currency saved", "success");
  };

  if (loading) return <div className="p-6"><div className="card p-8 text-center text-muted">Loading general settings...</div></div>;

  return (
    <div className="p-6 max-w-3xl">
      <div className="page-header">
        <h1 className="page-title">General Settings</h1>
        <p className="page-description">Settings for your own reports.</p>
      </div>
      {error && <div role="alert" className="mb-4 alert-error">{error}</div>}
      <form onSubmit={handleSubmit}>
        <div className="card p-5">
          <label htmlFor="base-currency" className="block font-medium">Base currency</label>
          <p className="text-sm text-muted">The reporting currency your statements consolidate into (ISO 4217, e.g. SGD, USD, EUR).</p>
          <input
            id="base-currency"
            aria-label="Base currency"
            type="text"
            value={draft ?? ""}
            disabled={submitting}
            maxLength={3}
            onChange={(e) => setDraft(e.target.value.toUpperCase())}
            className="input mt-3 w-32 uppercase"
          />
        </div>
        <div className="mt-4 flex items-center gap-3">
          <button type="submit" className="btn-primary" disabled={!isDirty || submitting}>
            {submitting ? "Saving..." : "Save changes"}
          </button>
          <button type="button" className="btn-secondary" onClick={reset} disabled={!isDirty || submitting}>Reset</button>
          {isDirty && !submitting && <span className="text-sm text-muted">Unsaved changes</span>}
        </div>
      </form>
    </div>
  );
}

const DEFAULT_SETTINGS: UserAiSettings = {
  enable_ai_reconciliation: false,
  enable_ai_classification: true,
  auto_accept_ai_suggestions: true,
  auto_accept_ai_suggestions_active: true,
};

const CHOICES = ["enable_ai_reconciliation", "enable_ai_classification", "auto_accept_ai_suggestions"] as const;

export function changedChoices(saved: UserAiSettings | null, next: UserAiSettings): UserAiSettingsUpdate {
  const body: UserAiSettingsUpdate = {};
  for (const key of CHOICES) {
    if (saved === null || saved[key] !== next[key]) body[key] = next[key];
  }
  return body;
}

export function AiSettingsPanel() {
  const { showToast } = useToast();
  const { saved, draft, setDraft, loading, submitting, error, isDirty, submit, reset } = useSettingsForm<UserAiSettings>({
    load: () => apiOperation("get_current_user_settings_users_me_settings_get"),
    save: (next, previous) =>
      apiOperation("patch_current_user_settings_users_me_settings_patch", { body: changedChoices(previous, next) }),
    isEqual: (a, b) => CHOICES.every((key) => a[key] === b[key]),
    loadErrorMessage: "Failed to load AI settings",
    saveErrorMessage: "Failed to save AI settings",
  });

  const operatorTurnedItOff =
    saved !== null &&
    saved.enable_ai_classification &&
    saved.auto_accept_ai_suggestions &&
    !saved.auto_accept_ai_suggestions_active;

  const setField = (key: (typeof CHOICES)[number], value: boolean) => {
    setDraft((prev) => ({ ...(prev ?? DEFAULT_SETTINGS), [key]: value }));
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const updated = await submit();
    if (updated !== null) showToast("AI settings saved", "success");
  };

  if (loading) return <div className="p-6"><div className="card p-8 text-center text-muted">Loading AI settings...</div></div>;
  if (!draft) return <div className="p-6 max-w-3xl"><div role="alert" className="alert-error">{error ?? "Failed to load AI settings"}</div></div>;

  return (
    <div className="p-6 max-w-3xl">
      <div className="page-header">
        <h1 className="page-title">AI Settings</h1>
        <p className="page-description">Control AI-assisted reconciliation, classification and automatic acceptance.</p>
      </div>
      <div className="mb-4">
        <Link href={`${NEEDS_YOU_HREF}#ai-suggestions`} className="btn-secondary inline-flex text-sm">Review AI suggestions</Link>
      </div>
      {error && <div role="alert" className="mb-4 alert-error">{error}</div>}
      <form onSubmit={handleSubmit}>
        <div className="card divide-y divide-[var(--border)]">
          <label className="p-5 flex items-center justify-between gap-4 cursor-pointer">
            <div>
              <div className="font-medium">Enable AI reconciliation</div>
              <p className="text-sm text-muted">Use semantic AI scoring for reconciliation candidates in the 60-84 review band.</p>
            </div>
            <input
              aria-label="Enable AI reconciliation"
              type="checkbox"
              checked={draft.enable_ai_reconciliation}
              disabled={submitting}
              onChange={(e) => setField("enable_ai_reconciliation", e.target.checked)}
              className="h-5 w-5 rounded"
            />
          </label>
          <label className="p-5 flex items-center justify-between gap-4 cursor-pointer">
            <div>
              <div className="font-medium">Enable AI classification</div>
              <p className="text-sm text-muted">AI classifies each transaction. High-confidence results post without manual review. Turn this off to review every transaction yourself.</p>
            </div>
            <input
              aria-label="Enable AI classification"
              type="checkbox"
              checked={draft.enable_ai_classification}
              disabled={submitting}
              onChange={(e) => setField("enable_ai_classification", e.target.checked)}
              className="h-5 w-5 rounded"
            />
          </label>
          <label className="p-5 flex items-center justify-between gap-4 cursor-pointer">
            <div>
              <div className="font-medium">Auto-accept AI suggestions</div>
              <p className="text-sm text-muted">
                The system accepts the AI suggestion for each transaction, so a statement posts without a click. A row that the AI cannot place goes to a general account. These entries show a low confidence tier. Turn this off to approve the uncertain rows yourself. It needs AI classification.
              </p>
              {operatorTurnedItOff && (
                <p role="note" className="text-sm text-muted mt-1">
                  The operator of this server turned the automatic acceptance off for all accounts. Your choice applies again when the operator turns it on.
                </p>
              )}
            </div>
            <input
              aria-label="Auto-accept AI suggestions"
              type="checkbox"
              checked={draft.auto_accept_ai_suggestions && draft.enable_ai_classification}
              disabled={submitting || !draft.enable_ai_classification}
              onChange={(e) => setField("auto_accept_ai_suggestions", e.target.checked)}
              className="h-5 w-5 rounded"
            />
          </label>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <button type="submit" className="btn-primary" disabled={!isDirty || submitting}>
            {submitting ? "Saving..." : "Save changes"}
          </button>
          <button type="button" className="btn-secondary" onClick={reset} disabled={!isDirty || submitting}>Reset</button>
          {isDirty && !submitting && <span className="text-sm text-muted">Unsaved changes</span>}
        </div>
      </form>
    </div>
  );
}

const SCENES: { scene: LlmScene; label: string; description: string }[] = [
  { scene: "extraction.ocr", label: "Extraction · OCR", description: "Read text from scanned documents." },
  { scene: "extraction.vision", label: "Extraction · Vision", description: "Understand statement layouts and tables." },
  { scene: "extraction.json", label: "Extraction · JSON", description: "Produce structured records from raw text." },
  { scene: "advisor.chat", label: "Advisor · Chat", description: "Answer grounded financial questions." },
  { scene: "statement.summary", label: "Statement · Summary", description: "Summarise an imported statement." },
];

const REASONING_OPTIONS: LlmReasoningEffort[] = ["none", "low", "medium", "high"];

function emptyBinding(scene: LlmScene): LlmSceneBindingItem {
  return { scene, provider_id: "", model: "", reasoning: "none", max_tokens: null };
}

function serialize(bindings: LlmSceneBindingItem[]): string {
  return JSON.stringify([...bindings].sort((a, b) => a.scene.localeCompare(b.scene)));
}

export function LlmSettingsPanel() {
  const { showToast } = useToast();
  const [providers, setProviders] = useState<LlmProviderResponse[]>([]);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [deletingProvider, setDeletingProvider] = useState(false);
  const [catalog, setCatalog] = useState<LlmModelResponse[]>([]);
  const [saved, setSaved] = useState<LlmSceneBindingItem[] | null>(null);
  const [draft, setDraft] = useState<LlmSceneBindingItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showProviderForm, setShowProviderForm] = useState(false);

  const mergeBindings = useCallback(
    (bindings: LlmSceneBindingItem[]): LlmSceneBindingItem[] =>
      SCENES.map(({ scene }) => bindings.find((b) => b.scene === scene) ?? emptyBinding(scene)),
    [],
  );

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [providerList, sceneList, catalogResponse] = await Promise.all([
        apiOperation("list_providers_llm_providers_get"),
        apiOperation("get_scenes_llm_scenes_get"),
        apiOperation("get_catalog_llm_catalog_get"),
      ]);
      setProviders(providerList.providers);
      setCatalog(catalogResponse.models);
      const merged = mergeBindings(sceneList.bindings);
      setSaved(merged);
      setDraft(merged);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load LLM settings");
    } finally {
      setLoading(false);
    }
  }, [mergeBindings]);

  useEffect(() => { void loadAll(); }, [loadAll]);

  const isDirty = useMemo(() => (saved && draft ? serialize(saved) !== serialize(draft) : false), [saved, draft]);

  const updateBinding = (scene: LlmScene, patch: Partial<LlmSceneBindingItem>) => {
    setDraft((prev) => (prev ?? []).map((b) => (b.scene === scene ? { ...b, ...patch } : b)));
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!draft || submitting) return;
    const configured = draft.filter((b) => b.provider_id !== "" && b.model.trim() !== "");
    setSubmitting(true);
    setError(null);
    try {
      const response = await apiOperation("put_scenes_llm_scenes_put", { body: { bindings: configured } });
      const merged = mergeBindings(response.bindings);
      setSaved(merged);
      setDraft(merged);
      showToast("LLM bindings saved", "success");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save LLM bindings");
    } finally {
      setSubmitting(false);
    }
  };

  const confirmDeleteProvider = async (id: string) => {
    setError(null);
    setDeletingProvider(true);
    try {
      await apiOperation("delete_provider_llm_providers__provider_id__delete", { path: { provider_id: id } });
      showToast("Provider deleted", "success");
      await loadAll();
      setPendingDeleteId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete provider");
    } finally {
      setDeletingProvider(false);
    }
  };

  if (loading) return <div className="p-6"><div className="card p-8 text-center text-muted">Loading LLM settings...</div></div>;
  if (!draft) return <div className="p-6 max-w-3xl"><div role="alert" className="alert-error">{error ?? "Failed to load LLM settings"}</div></div>;

  return (
    <div className="p-6 max-w-4xl">
      <div className="page-header">
        <h1 className="page-title">LLM Models</h1>
        <p className="page-description">Configure providers and bind each AI scene to a model.</p>
      </div>

      {error && <div role="alert" className="mb-4 alert-error">{error}</div>}

      <section className="mb-8">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Providers</h2>
          <button type="button" className="btn-secondary text-sm" onClick={() => setShowProviderForm((v) => !v)}>
            {showProviderForm ? "Close" : "Add provider"}
          </button>
        </div>

        {showProviderForm && (
          <div className="card p-5 mb-4">
            <ProviderForm
              onCreated={async () => {
                setShowProviderForm(false);
                showToast("Provider added", "success");
                await loadAll();
              }}
              onCancel={() => setShowProviderForm(false)}
            />
          </div>
        )}

        {providers.length === 0 ? (
          <div className="card p-5 text-sm text-muted">No providers configured yet. Add one to bind scenes to models.</div>
        ) : (
          <ul className="card divide-y divide-[var(--border)]">
            {providers.map((provider) => (
              <li key={provider.id} className="p-4 flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <div className="font-medium truncate">{provider.label}</div>
                  <div className="text-xs text-muted">{provider.protocol}{provider.api_base ? ` · ${provider.api_base}` : ""}</div>
                </div>
                <button
                  type="button"
                  className="btn-secondary text-sm"
                  aria-label={`Delete provider ${provider.label}`}
                  onClick={() => setPendingDeleteId(provider.id)}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <form onSubmit={handleSubmit}>
        <h2 className="mb-3 text-lg font-semibold">Task model assignments</h2>
        <div className="space-y-4">
          {SCENES.map(({ scene, label, description }) => {
            const binding = draft.find((b) => b.scene === scene)!;
            const sceneModels = catalog.filter((m) => m.provider_id === binding.provider_id);
            const listId = `models-${scene.replace(/\./g, "-")}`;
            return (
              <div key={scene} className="card p-5 space-y-3">
                <div>
                  <div className="font-medium">{label}</div>
                  <p className="text-sm text-muted">{description}</p>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <label htmlFor={`provider-${scene}`} className="block text-sm font-medium mb-1">Provider</label>
                    <select
                      id={`provider-${scene}`}
                      className="input w-full"
                      value={binding.provider_id}
                      disabled={submitting}
                      onChange={(e) => updateBinding(scene, { provider_id: e.target.value })}
                    >
                      <option value="">— Not configured —</option>
                      {providers.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
                    </select>
                  </div>
                  <div>
                    <label htmlFor={`model-${scene}`} className="block text-sm font-medium mb-1">Model</label>
                    <input
                      id={`model-${scene}`}
                      type="text"
                      className="input w-full"
                      list={listId}
                      value={binding.model}
                      disabled={submitting}
                      placeholder="e.g. openrouter/auto"
                      onChange={(e) => updateBinding(scene, { model: e.target.value })}
                    />
                    <datalist id={listId}>
                      {sceneModels.map((m) => <option key={m.id} value={m.id} />)}
                    </datalist>
                  </div>
                  <div>
                    <label htmlFor={`reasoning-${scene}`} className="block text-sm font-medium mb-1">Reasoning depth</label>
                    <select
                      id={`reasoning-${scene}`}
                      className="input w-full"
                      value={binding.reasoning}
                      disabled={submitting}
                      onChange={(e) => updateBinding(scene, { reasoning: e.target.value as LlmReasoningEffort })}
                    >
                      {REASONING_OPTIONS.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
                    </select>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div className="mt-4 flex items-center gap-3">
          <button type="submit" className="btn-primary" disabled={!isDirty || submitting}>
            {submitting ? "Saving..." : "Save changes"}
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => { if (saved) setDraft(saved); setError(null); }}
            disabled={!isDirty || submitting}
          >
            Reset
          </button>
          {isDirty && !submitting && <span className="text-sm text-muted">Unsaved changes</span>}
        </div>
      </form>

      <ConfirmDialog
        isOpen={pendingDeleteId !== null}
        title="Delete provider?"
        message={`Delete "${providers.find((p) => p.id === pendingDeleteId)?.label ?? "this provider"}"? Scenes bound to it fall back to the environment default. This cannot be undone.`}
        confirmLabel="Delete provider"
        confirmVariant="danger"
        loading={deletingProvider}
        onConfirm={() => { if (pendingDeleteId) void confirmDeleteProvider(pendingDeleteId); }}
        onCancel={() => setPendingDeleteId(null)}
      />
    </div>
  );
}

const ACCOUNT_TYPES = ["All", "ASSET", "LIABILITY", "EQUITY", "INCOME", "EXPENSE"] as const;

// The chart of accounts in the Accounts tab of `/settings` (`/settings?tab=accounts`).
export function AccountsPanel() {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [activeFilter, setActiveFilter] = useState<string>("All");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isOpeningBalanceOpen, setIsOpeningBalanceOpen] = useState(false);
  const [editingAccount, setEditingAccount] = useState<Account | null>(null);
  const [selectedAccount, setSelectedAccount] = useState<Account | null>(null);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["accounts"],
    queryFn: () => apiOperation("list_accounts_accounts_get", { query: { include_balance: true } }),
  });

  const { data: readiness } = useQuery({
    queryKey: ["opening-balance-readiness"],
    queryFn: () => apiOperation("get_opening_balance_readiness_status_accounts_opening_balance_readiness_get"),
  });

  const deleteMutation = useMutation({
    mutationFn: (accountId: string) =>
      apiOperation("delete_account_accounts__account_id__delete", { path: { account_id: accountId } }),
    onSuccess: () => {
      showToast("Account deleted successfully", "success");
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
    },
    onError: (err: Error) => {
      showToast(`Failed to delete account: ${err.message}`, "error");
    },
  });

  const deleteDialog = useConfirmDialog(async (accountId) => {
    try { await deleteMutation.mutateAsync(accountId); } catch {}
  });

  const accounts = data?.items ?? [];
  const filteredAccounts = activeFilter === "All" ? accounts : accounts.filter((a) => a.type === activeFilter);
  const groupedAccounts = filteredAccounts.reduce<Record<string, Account[]>>((groups, account) => {
    (groups[account.type] ??= []).push(account);
    return groups;
  }, {});

  return (
    <div className="p-4 sm:p-6">
      <PageHeader
        title="Accounts"
        description="Manage your chart of accounts"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" onClick={() => setIsOpeningBalanceOpen(true)} className="flex items-center gap-2">
              <Scale className="h-4 w-4" aria-hidden="true" />
              Set opening balances
            </Button>
            <Button onClick={() => { setEditingAccount(null); setIsModalOpen(true); }} className="flex items-center gap-2">
              <Plus className="h-4 w-4" aria-hidden="true" />
              Add Account
            </Button>
          </div>
        }
      />

      {readiness?.needs_opening_balance && (
        <Alert variant="warning" className="mb-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <span>
              Your balance sheet may be incomplete — you have activity
              {readiness.earliest_activity_date ? ` since ${readiness.earliest_activity_date}` : ""} but no opening balances recorded. Set your starting balances so reports tie out from day one.
            </span>
            <Button variant="secondary" onClick={() => setIsOpeningBalanceOpen(true)} className="shrink-0">
              Set opening balances
            </Button>
          </div>
        </Alert>
      )}

      <FilterTabs
        options={ACCOUNT_TYPES}
        value={activeFilter}
        onChange={setActiveFilter}
        className="mb-6 flex w-full flex-wrap gap-1 rounded-lg bg-[var(--background-muted)] p-1 sm:w-fit"
      />

      {error && (
        <Alert variant="error" className="mb-4">
          {error instanceof Error ? error.message : "Failed to load accounts"}
        </Alert>
      )}

      {isLoading ? (
        <LoadingState label="Loading accounts" />
      ) : error ? (
        <div className="card p-8 text-center" role="alert" aria-live="polite">
          <p className="text-[var(--foreground)] font-medium mb-2">Failed to load accounts</p>
          <p className="text-sm text-muted mb-6">{error instanceof Error ? error.message : "Unknown error"}</p>
          <Button variant="secondary" onClick={() => refetch()} aria-label="Retry loading accounts">Retry</Button>
        </div>
      ) : filteredAccounts.length === 0 ? (
        <EmptyState
          title="No accounts yet"
          action={<Button onClick={() => { setEditingAccount(null); setIsModalOpen(true); }}>Create First Account</Button>}
        />
      ) : (
        <div className="space-y-4">
          {Object.entries(groupedAccounts).map(([type, typeAccounts]) => (
            <div key={type} className="card">
              <div className="card-header flex items-center justify-between">
                <Badge variant="primary">{type}</Badge>
                <span className="text-xs text-muted">{typeAccounts.length} accounts</span>
              </div>
              <div className="divide-y divide-[var(--border)]">
                {typeAccounts.map((account) => (
                  <div
                    key={account.id}
                    data-testid={`account-row-${account.id}`}
                    className="flex cursor-pointer flex-col gap-3 px-4 py-4 transition-colors hover:bg-[var(--background-muted)]/50 sm:flex-row sm:items-center sm:justify-between sm:px-6"
                    onClick={() => setSelectedAccount(account)}
                  >
                    <div data-account-field="identity" className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="break-words font-medium">{account.name}</span>
                        {account.code && <span className="text-xs text-muted font-mono">{formatAccountCodeBadge(account.code)}</span>}
                        {!account.is_active && <Badge variant="muted">Inactive</Badge>}
                      </div>
                      {account.description && <p className="break-words text-xs text-muted sm:truncate">{account.description}</p>}
                    </div>
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-2">
                      <div data-account-field="balance" className="text-left sm:mr-2 sm:text-right">
                        <div className="font-semibold">{formatCurrencyLocale(account.balance ?? 0, account.currency)}</div>
                      </div>
                      <div data-account-field="actions" className="flex items-center gap-2">
                        <IconButton
                          icon={Pencil}
                          label="Edit Account"
                          onClick={(e) => { e.stopPropagation(); setEditingAccount(account); setIsModalOpen(true); }}
                          className="hover:text-[var(--accent)]"
                        />
                        <IconButton
                          icon={Trash2}
                          label="Delete Account"
                          onClick={(e) => { e.stopPropagation(); deleteDialog.open(account.id); }}
                          className="text-muted hover:text-[var(--error)]"
                          disabled={deleteMutation.isPending}
                        />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      <AccountFormModal
        isOpen={isModalOpen}
        onClose={() => { setIsModalOpen(false); setEditingAccount(null); }}
        onSuccess={() => queryClient.invalidateQueries({ queryKey: ["accounts"] })}
        editAccount={editingAccount}
      />

      <OpeningBalanceModal
        isOpen={isOpeningBalanceOpen}
        onClose={() => setIsOpeningBalanceOpen(false)}
        onSuccess={() => {
          showToast("Opening balances recorded", "success");
          queryClient.invalidateQueries({ queryKey: ["accounts"] });
          queryClient.invalidateQueries({ queryKey: ["opening-balance-readiness"] });
        }}
        accounts={accounts}
      />

      <ConfirmDialog
        isOpen={deleteDialog.isOpen}
        onCancel={deleteDialog.cancel}
        onConfirm={() => deleteDialog.confirm()}
        title="Delete Account"
        message="Are you sure you want to delete this account? This will only work if there are no transactions."
        confirmLabel="Delete Account"
        confirmVariant="danger"
        loading={deleteMutation.isPending}
      />

      <AccountDetailsSidebar
        account={selectedAccount}
        isOpen={!!selectedAccount}
        onClose={() => setSelectedAccount(null)}
      />
    </div>
  );
}

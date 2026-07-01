"use client";

import { useCallback, useEffect, useState } from "react";

import { AuditBackLink } from "@/components/audit/AuditBackLink";
import JournalEntryForm from "@/components/journal/JournalEntryForm";
import JournalEntryDetailsModal from "@/components/journal/JournalEntryDetailsModal";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import { FilterTabs } from "@/components/ui/FilterTabs";
import ConfidenceBadge from "@/components/ui/ConfidenceBadge";
import { EmptyState, LoadingState, StatusBadge } from "@/components/ui";
import { useToast } from "@/components/ui/Toast";
import { apiFetch } from "@/lib/api";
import { formatCurrencyLocale, sumAmounts } from "@/lib/audit/money";
import { formatDateDisplay } from "@/lib/date";
import { JournalEntry, JournalEntryListResponse, JournalLine } from "@/lib/types";

const STATUS_FILTERS = ["All", "draft", "posted", "reconciled", "void"] as const;

export default function JournalPage() {
    const { showToast } = useToast();
    const [entries, setEntries] = useState<JournalEntry[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [activeFilter, setActiveFilter] = useState<string>("All");
    const [isFormOpen, setIsFormOpen] = useState(false);

    const [selectedEntry, setSelectedEntry] = useState<JournalEntry | null>(null);

    const fetchEntries = useCallback(async () => {
        setLoading(true);
        try {
            const params = new URLSearchParams();
            if (activeFilter !== "All") params.set("status_filter", activeFilter);
            const data = await apiFetch<JournalEntryListResponse>(`/api/journal-entries?${params.toString()}`);
            setEntries(data.items);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to load entries");
        } finally {
            setLoading(false);
        }
    }, [activeFilter]);

    useEffect(() => {
        fetchEntries();
    }, [fetchEntries]);

    const calculateDebits = (lines: JournalLine[]) => {
        return sumAmounts(lines.filter((l) => l.direction === "DEBIT").map((line) => line.amount));
    };

    const handlePostEntry = async (entryId: string) => {
        try {
            await apiFetch(`/api/journal-entries/${entryId}/postings`, { method: "POST" });
            showToast("Entry posted successfully", "success");
            fetchEntries();
        } catch (err) {
            const message = err instanceof Error ? err.message : "Failed to post entry";
            showToast(message, "error");
            setError(message);
        }
    };

    const deleteDialog = useConfirmDialog(async (entryId) => {
        try {
            await apiFetch(`/api/journal-entries/${entryId}`, { method: "DELETE" });
            showToast("Draft entry deleted successfully", "success");
            fetchEntries();
        } catch (err) {
            const message = err instanceof Error ? err.message : "Failed to delete entry";
            showToast(message, "error");
            setError(message);
            throw err;
        }
    });

    const voidDialog = useConfirmDialog<[string]>(async (entryId, reason) => {
        try {
            await apiFetch(`/api/journal-entries/${entryId}/voidings`, {
                method: "POST",
                body: JSON.stringify({ reason }),
            });
            showToast("Entry voided successfully. Reversal entry created.", "success");
            fetchEntries();
        } catch (err) {
            const message = err instanceof Error ? err.message : "Failed to void entry";
            showToast(message, "error");
            setError(message);
            throw err;
        }
    });

    return (
        <div className="p-6">
            <div className="mb-4">
                <AuditBackLink />
            </div>
            {/* Header */}
            <div className="page-header flex items-center justify-between">
                <div>
                    <h1 className="page-title">Journal Entries</h1>
                    <p className="page-description">Record and review journal entries with balanced debits and credits</p>
                </div>
                <button onClick={() => setIsFormOpen(true)} className="btn-primary flex items-center gap-2">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                    </svg>
                    New Entry
                </button>
            </div>

            {/* Tabs */}
            <FilterTabs
                options={STATUS_FILTERS}
                value={activeFilter}
                onChange={setActiveFilter}
                capitalize
                className="flex gap-1 mb-6 bg-[var(--background-muted)] p-1 rounded-lg w-fit"
            />

            {/* Error */}
            {error && (
                <div className="mb-4 alert-error">
                    {error}
                </div>
            )}

            {/* Content */}
            {loading ? (
                <LoadingState label="Loading entries" />
            ) : error ? (
                <div className="card p-8 text-center" role="alert" aria-live="polite">
                    <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-[var(--error-muted)] text-[var(--error)] mb-4">
                        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                    </div>
                    <p className="text-[var(--foreground)] font-medium mb-2">Failed to load entries</p>
                    <p className="text-sm text-muted mb-6">{error}</p>
                    <button
                        onClick={fetchEntries}
                        className="btn-secondary"
                        aria-label="Retry loading journal entries"
                    >
                        Retry
                    </button>
                </div>
            ) : entries.length === 0 ? (
                <EmptyState
                    title="No journal entries yet"
                    action={<button onClick={() => setIsFormOpen(true)} className="btn-primary">Create First Entry</button>}
                />
            ) : (
                <div className="card">
                    <div className="divide-y divide-[var(--border)]">
                        {entries.map((entry) => {
                            const debits = calculateDebits(entry.lines);
                            return (
                                <div
                                    key={entry.id}
                                    className="px-6 py-4 hover:bg-[var(--background-muted)]/50 transition-colors cursor-pointer"
                                    onClick={() => setSelectedEntry(entry)}
                                >
                                    <div className="flex items-start justify-between gap-4">
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2 mb-1">
                                                <span className="font-medium truncate">{entry.memo}</span>
                                                <StatusBadge
                                                    status={entry.status}
                                                    variants={{ posted: "success", reconciled: "primary", void: "error" }}
                                                />
                                            </div>
                                            <div className="flex items-center gap-3 text-xs text-muted">
                                                <span>{formatDateDisplay(entry.entry_date)}</span>
                                                <span>•</span>
                                                <span>{entry.lines.length} lines</span>
                                                <span>•</span>
                                                <span className="capitalize">{entry.source_type.replace("_", " ")}</span>
                                                {entry.confidence_tier && (
                                                    <>
                                                        <span>•</span>
                                                        <ConfidenceBadge tier={entry.confidence_tier} />
                                                    </>
                                                )}
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-4">
                                            <div className="text-right">
                                                <div className="font-semibold">{formatCurrencyLocale(debits, entry.lines[0]?.currency || "SGD")}</div>
                                                <div className="text-xs text-muted">Total</div>
                                            </div>
                                            {entry.status === "draft" && (
                                                <div className="flex gap-2">
                                                    <button
                                                        onClick={(e) => { e.stopPropagation(); deleteDialog.open(entry.id); }}
                                                        className="btn-secondary text-xs py-1 px-2 text-[var(--error)] border-[var(--error)]/30 hover:bg-[var(--error-muted)]"
                                                    >
                                                        Delete
                                                    </button>
                                                    <button
                                                        onClick={(e) => { e.stopPropagation(); handlePostEntry(entry.id); }}
                                                        className="btn-primary text-xs py-1 px-2"
                                                    >
                                                        Post
                                                    </button>
                                                </div>
                                            )}
                                            {(entry.status === "posted" || entry.status === "reconciled") && (
                                                <button
                                                    onClick={(e) => { e.stopPropagation(); voidDialog.open(entry.id); }}
                                                    className="btn-secondary text-xs py-1 px-2 text-[var(--error)] border-[var(--error)]/30 hover:bg-[var(--error-muted)]"
                                                >
                                                    Void
                                                </button>
                                            )}
                                        </div>

                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}

            <JournalEntryForm isOpen={isFormOpen} onClose={() => setIsFormOpen(false)} onSuccess={fetchEntries} />

            <ConfirmDialog
                isOpen={voidDialog.isOpen}
                onCancel={voidDialog.cancel}
                onConfirm={(reason) => voidDialog.confirm(reason!)}
                title="Void Journal Entry"
                message="Are you sure you want to void this journal entry? A reversal entry will be created automatically."
                confirmLabel="Void Entry"
                confirmVariant="danger"
                showInput
                inputLabel="Void Reason"
                inputPlaceholder="Enter reason for voiding this entry..."
                inputRequired
                loading={voidDialog.isLoading}
            />

            <ConfirmDialog
                isOpen={deleteDialog.isOpen}
                onCancel={deleteDialog.cancel}
                onConfirm={() => deleteDialog.confirm()}
                title="Delete Journal Entry"
                message="Are you sure you want to delete this journal entry? This action cannot be undone."
                confirmLabel="Delete Entry"
                confirmVariant="danger"
                loading={deleteDialog.isLoading}
            />

            <JournalEntryDetailsModal
                entry={selectedEntry}
                isOpen={!!selectedEntry}
                onClose={() => setSelectedEntry(null)}
            />
        </div>
    );
}

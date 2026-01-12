"use client";

import { useCallback, useEffect, useState } from "react";

import JournalEntryForm from "@/components/journal/JournalEntryForm";
import { apiFetch } from "@/lib/api";
import { JournalEntry, JournalEntryListResponse, JournalLine } from "@/lib/types";

const STATUS_FILTERS = ["All", "draft", "posted", "reconciled", "void"] as const;

export default function JournalPage() {
    const [entries, setEntries] = useState<JournalEntry[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [activeFilter, setActiveFilter] = useState<string>("All");
    const [isFormOpen, setIsFormOpen] = useState(false);

    const fetchEntries = useCallback(async () => {
        setLoading(true);
        try {
            const params = new URLSearchParams();
            if (activeFilter !== "All") params.set("status", activeFilter);
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
        return lines.filter((l) => l.direction === "DEBIT").reduce((sum, l) => sum + l.amount, 0);
    };

    const handlePostEntry = async (entryId: string) => {
        try {
            await apiFetch(`/api/journal-entries/${entryId}/post`, { method: "POST" });
            fetchEntries();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to post entry");
        }
    };

    return (
        <div className="p-6">
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
            <div className="flex gap-1 mb-6 bg-[var(--background-muted)] p-1 rounded-lg w-fit">
                {STATUS_FILTERS.map((status) => (
                    <button
                        key={status}
                        onClick={() => setActiveFilter(status)}
                        className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors capitalize ${activeFilter === status
                            ? "bg-[var(--background-card)] text-[var(--foreground)]"
                            : "text-muted hover:text-[var(--foreground)]"
                            }`}
                    >
                        {status}
                    </button>
                ))}
            </div>

            {/* Error */}
            {error && (
                <div className="mb-4 alert-error">
                    {error}
                </div>
            )}

            {/* Content */}
            {loading ? (
                <div className="card p-8 text-center text-muted">
                    <div className="inline-block w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin mb-2" />
                    <p className="text-sm">Loading entries...</p>
                </div>
            ) : entries.length === 0 ? (
                <div className="card p-8 text-center">
                    <p className="text-muted mb-4">No journal entries yet</p>
                    <button onClick={() => setIsFormOpen(true)} className="btn-primary">Create First Entry</button>
                </div>
            ) : (
                <div className="card">
                    <div className="divide-y divide-[var(--border)]">
                        {entries.map((entry) => {
                            const debits = calculateDebits(entry.lines);
                            return (
                                <div key={entry.id} className="px-6 py-4 hover:bg-[var(--background-muted)]/50 transition-colors">
                                    <div className="flex items-start justify-between gap-4">
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2 mb-1">
                                                <span className="font-medium truncate">{entry.memo}</span>
                                                <span className={`badge ${entry.status === "posted" ? "badge-success" :
                                                    entry.status === "reconciled" ? "badge-primary" :
                                                        entry.status === "void" ? "badge-error" :
                                                            "badge-muted"
                                                    }`}>
                                                    {entry.status}
                                                </span>
                                            </div>
                                            <div className="flex items-center gap-3 text-xs text-muted">
                                                <span>{entry.entry_date}</span>
                                                <span>•</span>
                                                <span>{entry.lines.length} lines</span>
                                                <span>•</span>
                                                <span className="capitalize">{entry.source_type.replace("_", " ")}</span>
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-4">
                                            <div className="text-right">
                                                <div className="font-semibold">{debits.toLocaleString()}</div>
                                                <div className="text-xs text-muted">Total</div>
                                            </div>
                                            {entry.status === "draft" && (
                                                <button onClick={() => handlePostEntry(entry.id)} className="badge badge-success cursor-pointer hover:opacity-80">
                                                    Post
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
        </div>
    );
}

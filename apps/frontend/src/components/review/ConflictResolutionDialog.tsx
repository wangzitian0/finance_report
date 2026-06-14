"use client";

import { useId, useRef } from "react";
import { useFocusTrap } from "@/hooks/useFocusTrap";
import type { MoneyValue } from "@/lib/types";

interface ConflictCandidate {
    description: string;
    txn_date: string;
    amount: MoneyValue;
}

type ResolveAction = "confirm_distinct" | "link_transfer";

interface ConflictResolutionDialogProps {
    isOpen: boolean;
    onClose: () => void;
    duplicateCandidates: ConflictCandidate[];
    transferPairCandidates: ConflictCandidate[];
    /** #962: resolve the candidates so a legitimate conflict no longer blocks approval. */
    onResolve?: (action: ResolveAction) => void;
    isResolving?: boolean;
}

export function ConflictResolutionDialog({
    isOpen,
    onClose,
    duplicateCandidates,
    transferPairCandidates,
    onResolve,
    isResolving = false
}: ConflictResolutionDialogProps) {
    const dialogRef = useRef<HTMLDivElement>(null);
    const titleId = useId();
    useFocusTrap(dialogRef, isOpen);

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="absolute inset-0 bg-black/50" onClick={onClose} />
            <div
                ref={dialogRef}
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                onKeyDown={(e) => {
                    if (e.key === "Escape") onClose();
                }}
                className="relative bg-[var(--background-card)] border border-[var(--border)] rounded-lg shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col"
            >
                <div className="p-4 border-b border-[var(--border)] flex items-center justify-between">
                    <h2 id={titleId} className="text-lg font-semibold">Resolve Conflicts</h2>
                    <button
                        onClick={onClose}
                        aria-label="Close conflict resolution dialog"
                        className="text-muted hover:text-[var(--foreground)]"
                    >
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                    </button>
                </div>

                <div className="p-4 overflow-y-auto flex-1">
                    {duplicateCandidates.length === 0 && transferPairCandidates.length === 0 ? (
                        <div className="text-center py-8 text-muted">
                            <p>No conflicts detected for this statement.</p>
                        </div>
                    ) : (
                        <div className="space-y-6">
                            {duplicateCandidates.length > 0 && (
                                <div>
                                    <h3 className="text-sm font-medium mb-2 flex items-center gap-2">
                                        <span className="w-2 h-2 bg-[var(--warning)] rounded-full" />
                                        Duplicate Candidates
                                    </h3>
                                    <div className="space-y-2">
                                        {duplicateCandidates.map((c, i) => (
                                            <div key={i} className="p-3 border border-[var(--border)] rounded bg-[var(--background-muted)]/30 flex items-center justify-between">
                                                <div className="text-sm">
                                                    <div className="font-medium">{c.description}</div>
                                                    <div className="text-xs text-muted">{c.txn_date} • {c.amount}</div>
                                                </div>
                                                <button
                                                    type="button"
                                                    className="btn-primary btn-sm"
                                                    disabled={isResolving || !onResolve}
                                                    onClick={() => onResolve?.("confirm_distinct")}
                                                >
                                                    {isResolving ? "Resolving…" : "Resolve"}
                                                </button>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {transferPairCandidates.length > 0 && (
                                <div>
                                    <h3 className="text-sm font-medium mb-2 flex items-center gap-2">
                                        <span className="w-2 h-2 bg-[var(--accent)] rounded-full" />
                                        Transfer Pair Candidates
                                    </h3>
                                    <div className="space-y-2">
                                        {transferPairCandidates.map((c, i) => (
                                            <div key={i} className="p-3 border border-[var(--border)] rounded bg-[var(--background-muted)]/30 flex items-center justify-between">
                                                <div className="text-sm">
                                                    <div className="font-medium">{c.description}</div>
                                                    <div className="text-xs text-muted">{c.txn_date} • {c.amount}</div>
                                                </div>
                                                <button
                                                    type="button"
                                                    className="btn-primary btn-sm"
                                                    disabled={isResolving || !onResolve}
                                                    onClick={() => onResolve?.("link_transfer")}
                                                >
                                                    {isResolving ? "Resolving…" : "Link Pair"}
                                                </button>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    )}
                </div>

                <div className="p-4 border-t border-[var(--border)] flex justify-end">
                    <button onClick={onClose} className="btn-secondary">Close</button>
                </div>
            </div>
        </div>
    );
}

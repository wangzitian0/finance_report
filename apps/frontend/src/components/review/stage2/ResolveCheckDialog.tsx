import { useEffect, useId, useRef, useState } from "react";

import { useFocusTrap } from "@/hooks/useFocusTrap";

import { getCheckTypeLabel, type ConsistencyCheck } from "./types";

interface ResolveCheckDialogProps {
    check: ConsistencyCheck;
    actionLoading: boolean;
    onClose: () => void;
    onResolve: (action: string, note?: string) => void;
}

export function ResolveCheckDialog({ check, actionLoading, onClose, onResolve }: ResolveCheckDialogProps) {
    const [resolveNote, setResolveNote] = useState("");
    const resolveDialogRef = useRef<HTMLDivElement>(null);
    const resolveTitleId = useId();

    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.key === "Escape" && !actionLoading) {
                onClose();
            }
        };
        document.addEventListener("keydown", handleKeyDown);
        return () => document.removeEventListener("keydown", handleKeyDown);
    }, [actionLoading, onClose]);

    useFocusTrap(resolveDialogRef, true);

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
            <div className="fixed inset-0 bg-black/60" onClick={() => { if (!actionLoading) { onClose(); } }} aria-hidden="true" />
            <div ref={resolveDialogRef} role="dialog" aria-modal="true" aria-labelledby={resolveTitleId} className="relative z-10 w-full max-w-md card animate-slide-up">
                <div className="card-header">
                    <h2 id={resolveTitleId} className="text-lg font-semibold">Resolve Consistency Check</h2>
                </div>
                <div className="p-6 space-y-4">
                    <p className="text-sm text-muted">
                        <span className="font-medium text-[var(--foreground)]">{check.severity.toUpperCase()}</span>{" "}
                        {getCheckTypeLabel(check.check_type)} —{" "}
                        {(check.details.message as string | undefined) || JSON.stringify(check.details)}
                    </p>
                    <div>
                        <label htmlFor={`${resolveTitleId}-note`} className="block text-sm font-medium mb-1.5">Note (optional)</label>
                        <input
                            id={`${resolveTitleId}-note`}
                            type="text"
                            value={resolveNote}
                            onChange={(e) => setResolveNote(e.target.value)}
                            placeholder="Add resolution note..."
                            className="input"
                        />
                    </div>
                    <div className="flex gap-2 pt-2">
                        <button
                            type="button"
                            onClick={onClose}
                            className="btn-secondary flex-1"
                            disabled={actionLoading}
                        >
                            Cancel
                        </button>
                        <button
                            type="button"
                            onClick={() => onResolve("reject", resolveNote)}
                            className="btn-secondary flex-1 text-[var(--error)] border-[var(--error)]/30 hover:bg-[var(--error-muted)]"
                            disabled={actionLoading}
                        >
                            Reject
                        </button>
                        <button
                            type="button"
                            onClick={() => onResolve("flag", resolveNote)}
                            className="btn-secondary flex-1 text-[var(--warning)] border-[var(--warning)]/30 hover:bg-[var(--warning-muted)]"
                            disabled={actionLoading}
                        >
                            Flag
                        </button>
                        <button
                            type="button"
                            onClick={() => onResolve("approve", resolveNote)}
                            className="btn-primary flex-1"
                            disabled={actionLoading}
                        >
                            {actionLoading ? "Processing..." : "Approve"}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}

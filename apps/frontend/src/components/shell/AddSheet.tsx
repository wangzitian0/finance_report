"use client";

import { useState } from "react";
import { FileText, PencilLine } from "lucide-react";

import Sheet from "@/components/ui/Sheet";
import StatementUploader from "@/components/statements/StatementUploader";
import GuidedEvidenceForm from "@/components/assets/GuidedEvidenceForm";

type AddMode = "menu" | "upload" | "manual";

interface AddSheetProps {
    isOpen: boolean;
    onClose: () => void;
    onUploadComplete?: () => void;
}

// EPIC-022 AC22.21.2: the center "Add" action opens a sheet offering the two
// ways to feed the system — upload a statement (the AI identifies the type) or
// record something manually. It is an action, not a navigation route.
export default function AddSheet({ isOpen, onClose, onUploadComplete }: AddSheetProps) {
    const [mode, setMode] = useState<AddMode>("menu");

    const close = () => {
        setMode("menu");
        onClose();
    };

    const title = mode === "upload" ? "Upload statement" : mode === "manual" ? "Manual entry" : "Add";

    return (
        <Sheet isOpen={isOpen} onClose={close} title={title}>
            {mode === "menu" && (
                <div className="space-y-3">
                    <p className="text-sm text-muted">
                        Add new evidence. We identify uploaded statements automatically; the rest of
                        the work happens for you via notifications and review.
                    </p>
                    <button
                        type="button"
                        onClick={() => setMode("upload")}
                        className="flex w-full items-start gap-3 rounded-md border border-[var(--border)] p-4 text-left transition-colors hover:bg-[var(--background-muted)]"
                    >
                        <FileText className="mt-0.5 h-5 w-5 flex-shrink-0 text-[var(--accent)]" aria-hidden="true" />
                        <span>
                            <span className="block font-medium">Upload statement</span>
                            <span className="block text-xs text-muted">
                                PDF, CSV or image — the AI identifies the type
                            </span>
                        </span>
                    </button>
                    <button
                        type="button"
                        onClick={() => setMode("manual")}
                        className="flex w-full items-start gap-3 rounded-md border border-[var(--border)] p-4 text-left transition-colors hover:bg-[var(--background-muted)]"
                    >
                        <PencilLine className="mt-0.5 h-5 w-5 flex-shrink-0 text-[var(--accent)]" aria-hidden="true" />
                        <span>
                            <span className="block font-medium">Manual entry</span>
                            <span className="block text-xs text-muted">
                                ESOP / RSU, property, and other manual-trusted records
                            </span>
                        </span>
                    </button>
                </div>
            )}

            {mode === "upload" && (
                <StatementUploader
                    kind="statement"
                    onUploadComplete={() => {
                        onUploadComplete?.();
                        close();
                    }}
                />
            )}

            {mode === "manual" && <GuidedEvidenceForm />}
        </Sheet>
    );
}

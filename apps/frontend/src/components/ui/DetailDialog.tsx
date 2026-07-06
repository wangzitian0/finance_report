"use client";

import { useCallback, useEffect, useId, useRef } from "react";
import { useFocusTrap } from "@/hooks/useFocusTrap";
import { useBodyScrollLock } from "@/hooks/useBodyScrollLock";

interface DetailDialogProps {
    isOpen: boolean;
    onClose: () => void;
    title: string;
    children: React.ReactNode;
    maxWidth?: string;
}

export default function DetailDialog({
    isOpen,
    onClose,
    title,
    children,
    maxWidth = "max-w-lg",
}: DetailDialogProps) {
    const dialogRef = useRef<HTMLDivElement>(null);
    const titleId = useId();

    const handleClose = useCallback(() => {
        onClose();
    }, [onClose]);

    useEffect(() => {
        if (!isOpen) return;

        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.key === "Escape") {
                handleClose();
            }
        };

        document.addEventListener("keydown", handleKeyDown);
        return () => document.removeEventListener("keydown", handleKeyDown);
    }, [isOpen, handleClose]);

    useFocusTrap(dialogRef, isOpen);
    useBodyScrollLock(isOpen);

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div
                className="fixed inset-0 bg-black/60 animate-fade-in"
                onClick={handleClose}
                aria-hidden="true"
            />

            <div
                ref={dialogRef}
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                className={`relative z-10 w-full ${maxWidth} card animate-slide-up flex flex-col max-h-[90dvh]`}
            >
                <div className="card-header flex items-center justify-between">
                    <h2 id={titleId} className="text-lg font-semibold">{title}</h2>
                    <button
                        type="button"
                        onClick={handleClose}
                        className="p-2 -mr-2 text-muted hover:text-[var(--foreground)] transition-colors"
                    >
                        <span className="sr-only">Close modal</span>
                        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto overscroll-contain p-6">
                    {children}
                </div>
            </div>
        </div>
    );
}

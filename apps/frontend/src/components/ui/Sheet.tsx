"use client";

import { useCallback, useEffect, useId, useRef } from "react";
import { useFocusTrap } from "@/hooks/useFocusTrap";

interface SheetProps {
    isOpen: boolean;
    onClose: () => void;
    title: string;
    children: React.ReactNode;
    width?: string;
}

export default function Sheet({
    isOpen,
    onClose,
    title,
    children,
    width = "max-w-md",
}: SheetProps) {
    const sheetRef = useRef<HTMLDivElement>(null);
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

    useFocusTrap(sheetRef, isOpen);

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 overflow-hidden">
            <div 
                className="fixed inset-0 bg-black/60 transition-opacity animate-fade-in" 
                onClick={handleClose}
                aria-hidden="true"
            />

            <div className="fixed inset-y-0 right-0 flex pl-10">
                <div 
                    ref={sheetRef}
                    role="dialog"
                    aria-modal="true"
                    aria-labelledby={titleId}
                    className={`relative w-screen ${width} bg-[var(--background-card)] shadow-xl flex flex-col`}
                    style={{ 
                        animation: "slideInRight 0.3s ease-out forwards",
                    }}
                >
                    <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)]">
                        <h2 id={titleId} className="text-lg font-semibold">{title}</h2>
                        <button
                            type="button"
                            onClick={handleClose}
                            className="p-2 -mr-2 text-muted hover:text-[var(--foreground)] transition-colors"
                        >
                            <span className="sr-only">Close panel</span>
                            <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </button>
                    </div>
                    <div className="flex-1 overflow-y-auto p-6">
                        {children}
                    </div>
                </div>
            </div>
            <style>{`
                @keyframes slideInRight {
                    from { transform: translateX(100%); }
                    to { transform: translateX(0); }
                }
            `}</style>
        </div>
    );
}

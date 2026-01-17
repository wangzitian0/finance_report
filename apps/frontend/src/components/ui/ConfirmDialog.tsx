"use client";

import { useCallback, useEffect, useId, useState } from "react";

interface ConfirmDialogProps {
    isOpen: boolean;
    title: string;
    message: string;
    confirmLabel?: string;
    cancelLabel?: string;
    confirmVariant?: "danger" | "primary";
    showInput?: boolean;
    inputLabel?: string;
    inputPlaceholder?: string;
    inputRequired?: boolean;
    loading?: boolean;
    onConfirm: (inputValue?: string) => void;
    onCancel: () => void;
}

export default function ConfirmDialog({
    isOpen,
    title,
    message,
    confirmLabel = "Confirm",
    cancelLabel = "Cancel",
    confirmVariant = "primary",
    showInput = false,
    inputLabel,
    inputPlaceholder,
    inputRequired = false,
    loading = false,
    onConfirm,
    onCancel,
}: ConfirmDialogProps) {
    const [inputValue, setInputValue] = useState("");
    const titleId = useId();
    const inputId = useId();

    // Reset input value when dialog opens
    useEffect(() => {
        if (isOpen) {
            setInputValue("");
        }
    }, [isOpen]);

    const handleCancel = useCallback(() => {
        if (loading) return;
        setInputValue("");
        onCancel();
    }, [loading, onCancel]);

    // Handle ESC key to close dialog
    useEffect(() => {
        if (!isOpen) return;
        
        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.key === "Escape" && !loading) {
                handleCancel();
            }
        };
        
        document.addEventListener("keydown", handleKeyDown);
        return () => document.removeEventListener("keydown", handleKeyDown);
    }, [isOpen, loading, handleCancel]);

    if (!isOpen) return null;

    const handleConfirm = () => {
        if (showInput && inputRequired && !inputValue.trim()) {
            return;
        }
        onConfirm(showInput ? inputValue : undefined);
        setInputValue("");
    };

    const handleBackdropClick = () => {
        if (loading) return;
        handleCancel();
    };

    const confirmButtonClass = confirmVariant === "danger"
        ? "bg-[var(--error)] hover:bg-[var(--error)]/90 text-white"
        : "btn-primary";

    const isConfirmDisabled = loading || (showInput && inputRequired && !inputValue.trim());

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
            <div 
                className="fixed inset-0 bg-black/60" 
                onClick={handleBackdropClick}
                aria-hidden="true"
            />
            <div 
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                className="relative z-10 w-full max-w-md card animate-slide-up"
            >
                <div className="card-header">
                    <h2 id={titleId} className="text-lg font-semibold">{title}</h2>
                </div>

                <div className="p-6 space-y-4">
                    <p className="text-sm text-muted">{message}</p>

                    {showInput && (
                        <div>
                            {inputLabel && (
                                <label htmlFor={inputId} className="block text-sm font-medium mb-1.5">
                                    {inputLabel}
                                    {inputRequired && <span className="text-[var(--error)]"> *</span>}
                                </label>
                            )}
                            <textarea
                                id={inputId}
                                value={inputValue}
                                onChange={(e) => setInputValue(e.target.value)}
                                placeholder={inputPlaceholder}
                                rows={3}
                                className="input resize-none w-full"
                                autoFocus
                            />
                        </div>
                    )}

                    <div className="flex gap-3 pt-2">
                        <button
                            type="button"
                            onClick={handleCancel}
                            disabled={loading}
                            className="btn-secondary flex-1"
                        >
                            {cancelLabel}
                        </button>
                        <button
                            type="button"
                            onClick={handleConfirm}
                            disabled={isConfirmDisabled}
                            className={`flex-1 px-4 py-2 rounded-md font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${confirmButtonClass}`}
                        >
                            {loading ? (
                                <span className="flex items-center justify-center gap-2">
                                    <span className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
                                    Processing...
                                </span>
                            ) : confirmLabel}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}

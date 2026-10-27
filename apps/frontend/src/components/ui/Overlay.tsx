"use client";

import { useCallback, useEffect, useId, useRef, type RefObject } from "react";

const FOCUSABLE_SELECTOR =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

/**
 * Trap keyboard focus within a container element while active.
 * Moves initial focus to the first focusable child and cycles Tab / Shift+Tab.
 */
export function useFocusTrap(ref: RefObject<HTMLElement | null>, isActive: boolean): void {
  useEffect(() => {
    if (!isActive) return;
    const container = ref.current;
    if (!container) return;

    const focusable = container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
    const first = focusable[0];
    first?.focus();
    const trap = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      // Re-query on each keydown to avoid stale closure when DOM changes
      const currentFocusable = container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
      const firstEl = currentFocusable[0];
      const lastEl = currentFocusable[currentFocusable.length - 1];
      if (e.shiftKey && document.activeElement === firstEl) {
        e.preventDefault();
        lastEl?.focus();
      } else if (!e.shiftKey && document.activeElement === lastEl) {
        e.preventDefault();
        firstEl?.focus();
      }
    };

    container.addEventListener("keydown", trap);
    return () => container.removeEventListener("keydown", trap);
  }, [ref, isActive]);
}

// Ref-counted so overlapping overlays (e.g. a ConfirmDialog opened from inside a
// Sheet) don't unlock the body when the inner one closes while the outer is
// still open. Only the first lock disables scroll; only the last unlock
// restores it (#1608).
let lockCount = 0;
let savedOverflow = "";
let savedPaddingRight = "";

function applyLock(): void {
  const { body, documentElement } = document;
  savedOverflow = body.style.overflow;
  savedPaddingRight = body.style.paddingRight;
  // Compensate for the vanishing scrollbar so desktop content doesn't shift
  // sideways when the body locks.
  const scrollbar = window.innerWidth - documentElement.clientWidth;
  if (scrollbar > 0) {
    const current = parseFloat(getComputedStyle(body).paddingRight) || 0;
    body.style.paddingRight = `${current + scrollbar}px`;
  }
  body.style.overflow = "hidden";
}

function releaseLock(): void {
  document.body.style.overflow = savedOverflow;
  document.body.style.paddingRight = savedPaddingRight;
}

/**
 * Lock body scroll while `locked` is true. On mobile this stops the page behind
 * a modal/sheet from scrolling when the user drags inside the overlay.
 */
export function useBodyScrollLock(locked: boolean): void {
  useEffect(() => {
    if (!locked) return;
    if (lockCount === 0) applyLock();
    lockCount += 1;
    return () => {
      lockCount -= 1;
      if (lockCount === 0) releaseLock();
    };
  }, [locked]);
}

interface DetailDialogProps {
    isOpen: boolean;
    onClose: () => void;
    title: string;
    children: React.ReactNode;
    maxWidth?: string;
}

export function DetailDialog({
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

interface SheetProps {
    isOpen: boolean;
    onClose: () => void;
    title: string;
    children: React.ReactNode;
    width?: string;
}

export function Sheet({
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
    useBodyScrollLock(isOpen);

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
                    <div
                        className="flex-1 overflow-y-auto overscroll-contain p-6"
                        style={{ paddingBottom: "calc(1.5rem + env(safe-area-inset-bottom))" }}
                    >
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

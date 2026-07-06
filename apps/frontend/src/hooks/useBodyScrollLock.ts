"use client";

import { useEffect } from "react";

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

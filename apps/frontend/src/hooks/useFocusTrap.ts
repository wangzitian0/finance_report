"use client";

import { useEffect, type RefObject } from "react";

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
    const last = focusable[focusable.length - 1];
    first?.focus();

    const trap = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last?.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first?.focus();
      }
    };

    container.addEventListener("keydown", trap);
    return () => container.removeEventListener("keydown", trap);
  }, [ref, isActive]);
}
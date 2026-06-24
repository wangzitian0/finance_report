"use client";

import { useCallback, useState } from "react";

/**
 * State machine for a confirm/delete/void dialog, repeated verbatim across pages:
 * `{open, id, loading}` plus `open(id)` / `cancel()` / `confirm(...)` handlers.
 *
 * `onConfirm` does the page-specific work (API call + toast + refetch). The dialog
 * closes and resets only when `onConfirm` resolves; if it throws, the dialog stays
 * open (so `onConfirm` should surface its own error and rethrow to keep it open).
 * `cancel()` is a no-op while a confirm is in flight.
 */
export function useConfirmDialog<A extends unknown[] = []>(onConfirm: (id: string, ...args: A) => Promise<void>) {
  const [isOpen, setIsOpen] = useState(false);
  const [id, setId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const open = useCallback((targetId: string) => {
    setId(targetId);
    setIsOpen(true);
  }, []);

  const cancel = useCallback(() => {
    if (isLoading) return;
    setIsOpen(false);
    setId(null);
  }, [isLoading]);

  const confirm = useCallback(
    async (...args: A) => {
      if (id === null) return;
      setIsLoading(true);
      try {
        await onConfirm(id, ...args);
        setIsOpen(false);
        setId(null);
      } catch {
        // Keep the dialog open; onConfirm is responsible for surfacing the error.
      } finally {
        setIsLoading(false);
      }
    },
    [id, onConfirm],
  );

  return { isOpen, id, isLoading, open, cancel, confirm };
}

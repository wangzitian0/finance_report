"use client";

import { useCallback, useState } from "react";

export function useConfirmDialog<A extends unknown[] = []>(onConfirm: (id: string, ...args: A) => Promise<void>) {
  const [id, setId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const open = useCallback((targetId: string) => setId(targetId), []);
  const cancel = useCallback(() => {
    if (!isLoading) setId(null);
  }, [isLoading]);
  const confirm = useCallback(
    async (...args: A) => {
      if (id === null) return;
      setIsLoading(true);
      try {
        await onConfirm(id, ...args);
        setId(null);
      } catch {
        // Keep dialog open; onConfirm surfaces the error.
      } finally {
        setIsLoading(false);
      }
    },
    [id, onConfirm],
  );

  return { isOpen: id !== null, id, isLoading, open, cancel, confirm };
}

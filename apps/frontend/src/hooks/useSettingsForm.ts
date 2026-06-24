"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

interface UseSettingsFormOptions<T> {
  /** Load the persisted value (on mount and on `reload`). */
  load: () => Promise<T>;
  /** Persist the current draft; returns the new persisted value. */
  save: (draft: T) => Promise<T>;
  /** Dirty comparison; defaults to identity (`saved !== draft`). */
  isEqual?: (saved: T, draft: T) => boolean;
  loadErrorMessage?: string;
  saveErrorMessage?: string;
}

/**
 * The saved/draft settings form state machine repeated across the settings pages:
 * load → keep a `saved` baseline + an editable `draft`, expose `isDirty`, and a
 * `submit` that persists and re-baselines. State only — the page owns rendering and
 * any success toast (it can branch on `submit()`'s return: the new value, or `null`
 * if it no-opped/failed).
 */
export function useSettingsForm<T>({
  load,
  save,
  isEqual,
  loadErrorMessage = "Failed to load",
  saveErrorMessage = "Failed to save",
}: UseSettingsFormOptions<T>) {
  const [saved, setSaved] = useState<T | null>(null);
  const [draft, setDraft] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Hold the load/save callbacks in refs so the hook's own callbacks stay stable
  // even when the caller passes inline (non-memoized) `load`/`save` — otherwise the
  // mount effect would re-run on every render.
  const loadRef = useRef(load);
  loadRef.current = load;
  const saveRef = useRef(save);
  saveRef.current = save;

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const data = await loadRef.current();
      setSaved(data);
      setDraft(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : loadErrorMessage);
    } finally {
      setLoading(false);
    }
  }, [loadErrorMessage]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const isDirty = useMemo(() => {
    if (saved === null || draft === null) return false;
    return isEqual ? !isEqual(saved, draft) : saved !== draft;
  }, [saved, draft, isEqual]);

  const submit = useCallback(async (): Promise<T | null> => {
    if (submitting || !isDirty || draft === null) return null;
    setSubmitting(true);
    setError(null);
    try {
      const updated = await saveRef.current(draft);
      setSaved(updated);
      setDraft(updated);
      return updated;
    } catch (err) {
      setError(err instanceof Error ? err.message : saveErrorMessage);
      return null;
    } finally {
      setSubmitting(false);
    }
  }, [submitting, isDirty, draft, saveErrorMessage]);

  const reset = useCallback(() => {
    setDraft(saved);
    setError(null);
  }, [saved]);

  return { saved, draft, setDraft, loading, submitting, error, isDirty, submit, reset, reload };
}

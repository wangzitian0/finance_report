"use client";

import { useEffect, useState } from "react";

import { Badge, EmptyState, LoadingState } from "@/components/ui";
import { apiOperation } from "@/lib/api-client";
import { summarizeReplay } from "@/lib/confidence";
import type { CorrectionLoopReplayResponse } from "@/lib/types";

/** Shows how past confirmations reduce extraction errors on new statements. */
export function CorrectionLoopProof() {
  const [replay, setReplay] = useState<CorrectionLoopReplayResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setReplay(null);
    setError(null);
    void (async () => {
      try {
        const result = await apiOperation("get_correction_loop_replay_metrics_correction_loop_replay_get");
        if (active) setReplay(result);
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Failed to load correction-loop proof");
      }
    })();
    return () => { active = false; };
  }, [attempt]);

  const summary = replay ? summarizeReplay(replay) : null;

  return (
    <div className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold">Correction Loop Proof</h2>
        <p className="text-xs text-muted">See how your past reviews improve automatic statement reading.</p>
      </div>
      {replay === null && !error && <LoadingState label="Loading correction-loop proof" />}
      {error && <EmptyState role="alert" title="Couldn't load correction-loop proof" description={error} action={<button onClick={() => setAttempt((v) => v + 1)} className="btn-secondary text-sm">Retry</button>} />}
      {summary && !error && (
        <section className="card p-5">
          <div className="flex items-center justify-between gap-3">
            <h3 className="font-semibold">Held-out replay</h3>
            {summary.hasHoldout && <Badge variant={summary.reduced ? "success" : "muted"}>{summary.reduced ? "Improves extraction" : "No measurable improvement"}</Badge>}
          </div>
          <p className="mt-1 text-sm text-muted">Shows how past review corrections reduce extraction errors on new statements.</p>
          {summary.hasHoldout ? (
            <div className="mt-4 grid grid-cols-1 gap-3 text-center sm:grid-cols-2">
              <div className="rounded-md bg-[var(--background-muted)] p-3"><p className="text-2xl font-semibold tabular-nums">{summary.before}</p><p className="mt-1 text-xs text-muted">Before correction reuse</p></div>
              <div className="rounded-md bg-[var(--background-muted)] p-3"><p className="text-2xl font-semibold tabular-nums">{summary.after}</p><p className="mt-1 text-xs text-muted">After correction reuse</p></div>
            </div>
          ) : (
            <EmptyState framed={false} className="mt-4" title="Not enough correction history yet" description="A held-out proof appears after enough recurring corrections exist." />
          )}
        </section>
      )}
    </div>
  );
}

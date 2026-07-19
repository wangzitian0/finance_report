"use client";

import { useEffect, useState } from "react";

import { AuditBackLink } from "@/components/audit/AuditBackLink";
import { Badge, EmptyState, LoadingState, PageHeader } from "@/components/ui";
import { fetchCorrectionLoopReplay } from "@/lib/api";
import { summarizeReplay } from "@/lib/confidence";
import type { CorrectionLoopReplayResponse } from "@/lib/types";

export default function CorrectionLoopPage() {
  const [replay, setReplay] = useState<CorrectionLoopReplayResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setReplay(null);
    setError(null);
    const load = async () => {
      try {
        const result = await fetchCorrectionLoopReplay();
        if (active) setReplay(result);
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : "Failed to load correction-loop proof");
        }
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, [attempt]);

  return (
    <div className="p-6">
      <div className="mb-4">
        <AuditBackLink />
      </div>
      <PageHeader
        title="Correction Loop Proof"
        description="Held-out replay measures whether recurring corrections improve future extraction without treating source labels as financial authority."
      />

      {replay === null && !error && <LoadingState label="Loading correction-loop proof" />}
      {error && (
        <EmptyState
          role="alert"
          title="Couldn't load correction-loop proof"
          description={error}
          action={
            <button onClick={() => setAttempt((value) => value + 1)} className="btn-secondary text-sm">
              Retry
            </button>
          }
        />
      )}
      {replay !== null && !error && <ReplayCard replay={replay} />}
    </div>
  );
}

function ReplayCard({ replay }: { replay: CorrectionLoopReplayResponse }) {
  const summary = summarizeReplay(replay);

  return (
    <section className="card p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-semibold">Held-out replay</h2>
        {summary.hasHoldout && (
          <Badge variant={summary.reduced ? "success" : "muted"}>
            {summary.reduced ? "Improves extraction" : "No measurable improvement"}
          </Badge>
        )}
      </div>
      <p className="mt-1 text-sm text-muted">
        This evaluates correction reuse on held-out examples. Package trust remains a separate
        TraceRecord decision.
      </p>

      {summary.hasHoldout ? (
        <div className="mt-4 grid grid-cols-1 gap-3 text-center sm:grid-cols-2">
          <div className="rounded-md bg-[var(--background-muted)] p-3">
            <p className="text-2xl font-semibold tabular-nums">{summary.before}</p>
            <p className="mt-1 text-xs text-muted">Before correction reuse</p>
          </div>
          <div className="rounded-md bg-[var(--background-muted)] p-3">
            <p className="text-2xl font-semibold tabular-nums">{summary.after}</p>
            <p className="mt-1 text-xs text-muted">After correction reuse</p>
          </div>
        </div>
      ) : (
        <EmptyState
          framed={false}
          className="mt-4"
          title="Not enough correction history yet"
          description="A held-out proof appears after enough recurring corrections exist."
        />
      )}
    </section>
  );
}

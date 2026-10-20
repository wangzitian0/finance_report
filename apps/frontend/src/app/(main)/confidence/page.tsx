"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AuditBackLink } from "@/components/audit/AuditBackLink";
import { Badge, EmptyState, LoadingState, PageHeader } from "@/components/ui";
import { apiOperation } from "@/lib/api-client";
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
        const result = await apiOperation(
          "get_correction_loop_replay_metrics_correction_loop_replay_get",
        );
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
        description="See items that need your confirmation and how your past reviews improve automatic statement reading."
      />

      <div className="card p-4 mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-sm font-semibold">Review items needing attention</h2>
          <p className="mt-0.5 text-xs text-muted">
            Inspect low-confidence statement lines and unmatched transactions in one ranked queue.
          </p>
        </div>
        <Link href="/attention" className="btn-primary text-xs px-3 py-1.5 w-fit">
          Open attention queue
        </Link>
      </div>

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
        Shows how past review corrections reduce extraction errors on new statements.
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

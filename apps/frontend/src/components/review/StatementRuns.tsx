"use client";

import { useState, type FormEvent } from "react";
import { formatDateTimeDisplay } from "@/lib/date";
import { humanizeIdentifier } from "@/lib/statusLabels";
import type { StatementRun, StatementRunHints } from "@/lib/types";

// The limits of the backend `RunHints` model (extraction/base/types.py). The server checks them again.
export const HINT_MAX_KEYWORDS = 20;
export const HINT_KEYWORD_MAX_LENGTH = 64;
export const HINT_NOTE_MAX_LENGTH = 500;

export const isRunActive = (run: StatementRun): boolean => run.state === "requested" || run.state === "running";

/** Split the keyword field on commas and new lines. Trim each keyword and drop the empty ones. */
export function parseKeywords(text: string): string[] {
  return text.split(/[,\n]/).map((keyword) => keyword.trim()).filter((keyword) => keyword.length > 0);
}

export function keywordProblem(keywords: string[]): string | null {
  if (keywords.length > HINT_MAX_KEYWORDS) return `Use at most ${HINT_MAX_KEYWORDS} keywords.`;
  if (keywords.some((keyword) => keyword.length > HINT_KEYWORD_MAX_LENGTH)) return `Each keyword has at most ${HINT_KEYWORD_MAX_LENGTH} characters.`;
  return null;
}

const STATE_TONE: Record<string, string> = {
  succeeded: "text-[var(--success)]",
  failed: "text-[var(--error)]",
  requested: "text-[var(--accent)]",
  running: "text-[var(--accent)]",
};

export function ParsingAttempts({ runs }: { runs: readonly StatementRun[] }) {
  const newestFirst = [...runs].sort((a, b) => b.seq - a.seq);
  return (
    <section aria-labelledby="parsing-attempts-heading" data-testid="parsing-attempts" className="card p-4">
      <h2 id="parsing-attempts-heading" className="font-semibold text-[var(--foreground)]">Parsing attempts</h2>
      {newestFirst.length === 0 ? (
        <p className="mt-2 text-sm text-muted">No attempt is recorded for this statement.</p>
      ) : (
        <ol className="mt-3 space-y-3">
          {newestFirst.map((run) => {
            const keywords = run.hints.keywords ?? [];
            const note = run.hints.note ?? "";
            return (
              <li key={run.id} data-testid={`parsing-attempt-${run.seq}`} className="border-t border-[var(--border)] pt-3 text-sm first:border-t-0 first:pt-0">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="font-medium">Attempt {run.seq}</span>
                  <span className="text-muted">{humanizeIdentifier(run.actor_kind)} · {humanizeIdentifier(run.trigger)}</span>
                  <span className={`font-medium ${STATE_TONE[run.state] ?? "text-muted"}`}>{humanizeIdentifier(run.state)}</span>
                  <time dateTime={run.requested_at} className="text-xs text-muted">{formatDateTimeDisplay(run.requested_at)}</time>
                </div>
                {keywords.length > 0 && (
                  <ul aria-label={`Keywords of attempt ${run.seq}`} className="mt-1.5 flex flex-wrap gap-1.5">
                    {keywords.map((keyword, index) => (
                      <li key={`${keyword}-${index}`} className="rounded-full border border-[var(--border)] bg-[var(--background-muted)] px-2 py-0.5 text-xs">{keyword}</li>
                    ))}
                  </ul>
                )}
                {note && <p className="mt-1.5 whitespace-pre-wrap break-words text-muted">Note: {note}</p>}
                {keywords.length === 0 && !note && <p className="mt-1 text-xs text-muted">No hints</p>}
                {run.error_code && <p className="mt-1 text-xs text-[var(--error)]">Error: {run.error_code}</p>}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

export function RunAgainPanel({ activeRun, pending, errorMessage, onRun }: {
  activeRun: boolean;
  pending: boolean;
  errorMessage: string | null;
  /** Start the run. Resolve true when it started: the panel then clears its fields. */
  onRun: (hints: StatementRunHints) => Promise<boolean>;
}) {
  const [keywordText, setKeywordText] = useState("");
  const [note, setNote] = useState("");
  const keywords = parseKeywords(keywordText);
  const problem = keywordProblem(keywords);
  const disabled = activeRun || pending || problem !== null;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (disabled) return;
    const started = await onRun({ keywords, note: note.trim() ? note : null });
    if (started) {
      setKeywordText("");
      setNote("");
    }
  };

  return (
    <form onSubmit={submit} aria-labelledby="run-again-heading" data-testid="run-again-panel" className="card p-4">
      <h2 id="run-again-heading" className="font-semibold text-[var(--foreground)]">Run again</h2>
      <p className="mt-1 text-sm text-muted">Add keywords or a note to guide the next parse. The result still passes the same checks.</p>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <label className="block text-sm">
          <span className="mb-1.5 block font-medium">Keywords</span>
          <textarea
            value={keywordText}
            onChange={(event) => setKeywordText(event.target.value)}
            rows={3}
            placeholder="interest, FX fee"
            aria-describedby="run-again-keyword-help"
            className="input w-full resize-none"
          />
          <span id="run-again-keyword-help" className="mt-1 block text-xs text-muted">
            Separate with commas or new lines. Up to {HINT_MAX_KEYWORDS} keywords of {HINT_KEYWORD_MAX_LENGTH} characters.
          </span>
        </label>
        <label className="block text-sm">
          <span className="mb-1.5 block font-medium">Note</span>
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            rows={3}
            maxLength={HINT_NOTE_MAX_LENGTH}
            placeholder="What should the parser look at?"
            className="input w-full resize-none"
          />
          <span className="mt-1 block text-xs text-muted">{note.length} / {HINT_NOTE_MAX_LENGTH}</span>
        </label>
      </div>
      {problem && <p role="alert" className="mt-2 text-sm text-[var(--error)]">{problem}</p>}
      {activeRun && <p role="status" className="mt-2 text-sm text-muted">A parse is running. You can run again when it ends.</p>}
      {errorMessage && <p role="alert" className="mt-2 text-sm text-[var(--error)]">{errorMessage}</p>}
      <div className="mt-3">
        <button type="submit" disabled={disabled} className="btn-primary disabled:cursor-not-allowed disabled:opacity-50">
          {pending ? "Starting..." : "Run again"}
        </button>
      </div>
    </form>
  );
}

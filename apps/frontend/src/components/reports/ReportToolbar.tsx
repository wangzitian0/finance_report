"use client";

import Link from "next/link";
import type { ReactNode } from "react";

/**
 * Report toolbar primitives (Slice 3 of #751).
 *
 * The "AI Interpretation / Home / Export CSV" action cluster was duplicated
 * verbatim across every report route. `ReportToolbar` composes it from props so
 * routes only supply the prompt text and the export control; `AiPromptAction` is
 * the standalone AI link used inside it.
 *
 * As a pure UI primitive, `ReportToolbar` does NOT import any API/transport code
 * (#751 dependency rule). The export control is caller-provided via the
 * `exportControl` slot: the page (or a hook) wires `apiDownload` + the export
 * path and passes the rendered control in.
 */

interface AiPromptActionProps {
  /** Natural-language prompt; URL-encoded into the chat route. */
  prompt: string;
  label?: string;
}

export function AiPromptAction({ prompt, label = "AI Interpretation" }: AiPromptActionProps) {
  return (
    <Link href={`/chat?prompt=${encodeURIComponent(prompt)}`} className="btn-secondary text-sm">
      {label}
    </Link>
  );
}

interface ReportToolbarProps {
  /** Natural-language prompt for the AI interpretation action. */
  aiPrompt: string;
  /**
   * Caller-provided export control (e.g. `<ExportCsvButton />`). The page owns
   * the API/transport wiring so this primitive stays free of `@/lib/api`.
   */
  exportControl?: ReactNode;
  /** Destination for the "Home" link. */
  homeHref?: string;
  /** Optional extra actions rendered before the standard cluster. */
  children?: ReactNode;
}

export function ReportToolbar({
  aiPrompt,
  exportControl,
  homeHref = "/",
  children,
}: ReportToolbarProps) {
  return (
    <div className="flex gap-2 flex-wrap">
      {children}
      <AiPromptAction prompt={aiPrompt} />
      <Link href={homeHref} className="btn-secondary text-sm">
        Home
      </Link>
      {exportControl}
    </div>
  );
}

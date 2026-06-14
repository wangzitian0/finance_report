"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { ExportCsvButton } from "@/components/reports/ExportCsvButton";

/**
 * Report toolbar primitives (Slice 3 of #751).
 *
 * The "AI Interpretation / Home / Export CSV" action cluster was duplicated
 * verbatim across every report route. `ReportToolbar` composes it from props so
 * routes only supply the prompt text and export path; `AiPromptAction` is the
 * standalone AI link used inside it.
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
  /** Authenticated CSV export path. */
  exportPath: string;
  /** Destination for the "Home" link. */
  homeHref?: string;
  /** Optional extra actions rendered before the standard cluster. */
  children?: ReactNode;
}

export function ReportToolbar({
  aiPrompt,
  exportPath,
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
      <ExportCsvButton path={exportPath} />
    </div>
  );
}

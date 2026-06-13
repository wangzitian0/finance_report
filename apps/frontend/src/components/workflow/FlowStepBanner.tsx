"use client";

import Link from "next/link";
import { Check, ChevronRight } from "lucide-react";

// EPIC-022 AC22.5.1: a shared "you are here / what's next" indicator across the
// core flow so an everyday user always knows where they are in
// Upload -> Review & approve -> Reports.
export type FlowStep = "upload" | "review" | "reports";

interface FlowStepConfig {
    key: FlowStep;
    label: string;
    href: string;
}

const STEPS: FlowStepConfig[] = [
    { key: "upload", label: "Upload", href: "/upload" },
    { key: "review", label: "Review & approve", href: "/notifications" },
    { key: "reports", label: "Reports", href: "/reports" },
];

const NEXT_HINT: Record<FlowStep, string> = {
    upload: "Next: once we parse your statement, review and approve it.",
    review: "Next: approve to post entries — your reports update automatically.",
    reports: "You're all set. Open any amount to trace it back to its source.",
};

export function FlowStepBanner({ current }: { current: FlowStep }) {
    const currentIndex = STEPS.findIndex((step) => step.key === current);

    return (
        <nav
            aria-label="Upload to reports progress"
            className="card flex flex-col gap-2 p-3 sm:flex-row sm:items-center sm:justify-between"
        >
            <ol className="flex items-center gap-1 text-sm">
                {STEPS.map((step, index) => {
                    const isCurrent = step.key === current;
                    const isDone = index < currentIndex;
                    return (
                        <li key={step.key} className="flex items-center gap-1">
                            <Link
                                href={step.href}
                                aria-current={isCurrent ? "step" : undefined}
                                className={`inline-flex items-center gap-1.5 rounded-md px-2 py-1 transition-colors ${
                                    isCurrent
                                        ? "bg-[var(--accent-muted)] font-semibold text-[var(--accent)]"
                                        : "text-muted hover:text-[var(--foreground)]"
                                }`}
                            >
                                <span
                                    aria-hidden="true"
                                    className={`flex h-5 w-5 items-center justify-center rounded-full text-xs ${
                                        isCurrent
                                            ? "bg-[var(--accent)] text-white"
                                            : isDone
                                              ? "bg-[var(--success-muted)] text-[var(--success)]"
                                              : "bg-[var(--background-muted)] text-muted"
                                    }`}
                                >
                                    {isDone ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : index + 1}
                                </span>
                                {step.label}
                            </Link>
                            {index < STEPS.length - 1 && (
                                <span aria-hidden="true" className="px-1 text-muted">
                                    <ChevronRight className="h-4 w-4" />
                                </span>
                            )}
                        </li>
                    );
                })}
            </ol>
            <p className="text-xs text-muted">{NEXT_HINT[current]}</p>
        </nav>
    );
}

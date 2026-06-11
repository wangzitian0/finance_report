"use client";

// EPIC-022 AC22.5.5: a tiny, dependency-free affordance that attaches a
// plain-language explanation to the accounting/system jargon an everyday user
// would otherwise meet unexplained. Mirrors the existing `title`-attribute
// convention used by ConfidenceBadge, and exposes the same text to assistive
// tech via aria-label so the hint is not mouse-only.

export const GLOSSARY = {
    balanced: "Your books balance: assets equal liabilities plus equity.",
    drift: "Your books don't balance yet — assets don't equal liabilities plus equity. Usually a missing or miscategorised entry.",
    needs_review:
        "We parsed this statement, but its totals need a human check before it updates your reports.",
    transfer_pair:
        "Two transactions that look like the same money moving between your own accounts — counting both would double it.",
    anomaly: "Something unusual about this match (an unexpected amount or date) that's worth a quick look.",
    duplicate: "This looks like a transaction we already have, so approving both would double-count it.",
    consistency_check:
        "An automatic check for duplicates, transfers, and anomalies before matches are approved.",
    match_score: "How confident we are that a bank transaction and a ledger entry are the same thing (0–100).",
} as const;

export type GlossaryTerm = keyof typeof GLOSSARY;

interface InfoHintProps {
    term: GlossaryTerm;
    /** Human label for the term, used to prefix the accessible description. */
    label?: string;
    className?: string;
}

export function InfoHint({ term, label, className }: InfoHintProps) {
    const text = GLOSSARY[term];
    const description = label ? `${label}: ${text}` : text;
    return (
        <span
            role="img"
            tabIndex={0}
            aria-label={description}
            title={text}
            className={`ml-1 inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full border border-current text-[10px] leading-none text-muted align-middle ${className ?? ""}`}
        >
            i
        </span>
    );
}

"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";

import { auditHubItems } from "@/components/navigation";
import { PageHeader } from "@/components/ui";

// EPIC-022 AC22.21.3: the Audit hub is a verify-on-demand surface. It folds the
// accounting machinery (confidence/trust, reconciliation, journal, processing)
// out of navigation into one place the user visits only when they want to check
// "is this number real?" — each card deep-links to the existing page.
const DESCRIPTIONS: Record<string, string> = {
    "/confidence": "How trusted each number is — confirmations needed and low-confidence items.",
    "/reconciliation": "How well your statements reconcile, and anything still unmatched.",
    "/journal": "The double-entry ledger behind every figure in your reports.",
    "/processing": "The status of statements still being parsed or transformed.",
};

export default function AuditPage() {
    return (
        <div className="p-6">
            <PageHeader
                title="Audit"
                description="Everything behind your numbers. Browse here whenever you want to verify a figure — the day-to-day work that needs you is pushed to your inbox."
            />

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {auditHubItems.map((item) => {
                    const Icon = item.icon;
                    return (
                        <Link
                            key={item.href}
                            href={item.href}
                            className="card flex items-start gap-3 p-4 transition-colors hover:bg-[var(--background-muted)]"
                        >
                            <span className="mt-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-md bg-[var(--accent-muted)] text-[var(--accent)]">
                                <Icon className="h-5 w-5" aria-hidden="true" />
                            </span>
                            <span className="min-w-0 flex-1">
                                <span className="flex items-center justify-between gap-2">
                                    <span className="font-medium">{item.label}</span>
                                    <ChevronRight className="h-4 w-4 flex-shrink-0 text-muted" aria-hidden="true" />
                                </span>
                                <span className="mt-0.5 block text-xs text-muted">{DESCRIPTIONS[item.href]}</span>
                            </span>
                        </Link>
                    );
                })}
            </div>
        </div>
    );
}

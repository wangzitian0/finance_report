"use client";

import Link from "next/link";
import type { ReactNode } from "react";

// EPIC-022 AC22.5.3: a small back-link so users who deep-link into a review or
// reconciliation surface are never stranded. Defaults back to the notification
// center, which is the action hub in the EPIC-022 IA.
export function BackLink({ href = "/notifications", children }: { href?: string; children: ReactNode }) {
    return (
        <Link
            href={href}
            className="inline-flex items-center gap-1 text-sm text-muted hover:text-[var(--foreground)]"
        >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            {children}
        </Link>
    );
}

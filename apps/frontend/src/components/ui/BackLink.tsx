"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import type { ReactNode } from "react";
import { ChevronLeft } from "lucide-react";

import {
    ATTENTION_RETURN_HREF,
    ATTENTION_RETURN_LABEL,
    isAttentionOrigin,
} from "@/lib/attentionNavigation";

// EPIC-022 AC22.5.3: a small back-link so users who deep-link into a review or
// reconciliation surface are never stranded. Defaults back to the notification
// center, which is the action hub in the EPIC-022 IA.
export function BackLink({ href = "/notifications", children }: { href?: string; children: ReactNode }) {
    const searchParams = useSearchParams();
    const attentionOrigin = isAttentionOrigin(searchParams);
    const targetHref = attentionOrigin ? ATTENTION_RETURN_HREF : href;
    const label = attentionOrigin ? ATTENTION_RETURN_LABEL : children;

    return (
        <Link
            href={targetHref}
            className="inline-flex items-center gap-1 text-sm text-muted hover:text-[var(--foreground)]"
        >
            <ChevronLeft className="h-4 w-4" aria-hidden="true" />
            {label}
        </Link>
    );
}

"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";
import { ChevronLeft } from "lucide-react";

import {
  ATTENTION_RETURN_HREF,
  ATTENTION_RETURN_LABEL,
  isAttentionOrigin,
} from "@/lib/attentionNavigation";

interface SmartBackLinkProps {
  fallbackHref?: string;
  fallbackLabel?: string;
  children?: ReactNode;
  className?: string;
}

/**
 * Smart back navigation link (BUG-10, EPIC-022 AC22.5.3).
 *
 * Checks attention origin first, then explicit return_to parameter,
 * then browser history if accessible, and finally defaults to
 * a contextually sensible fallback (e.g. /dashboard or provided fallback).
 */
export function SmartBackLink({
  fallbackHref = "/dashboard",
  fallbackLabel = "Back to Dashboard",
  children,
  className = "",
}: SmartBackLinkProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const attentionOrigin = isAttentionOrigin(searchParams);
  const returnTo = searchParams.get("return_to");

  const targetHref = attentionOrigin
    ? ATTENTION_RETURN_HREF
    : returnTo || fallbackHref;

  const label = attentionOrigin
    ? ATTENTION_RETURN_LABEL
    : children || (returnTo ? "Back" : fallbackLabel);

  const handleClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
    // If attention origin or explicit return_to, let Link navigate to target
    if (attentionOrigin || returnTo) return;

    // If browser has history within this app, navigate back
    if (typeof window !== "undefined" && window.history.length > 2) {
      e.preventDefault();
      router.back();
    }
  };

  return (
    <Link
      href={targetHref}
      onClick={handleClick}
      data-testid="smart-back-link"
      className={`inline-flex items-center gap-1 text-sm text-muted hover:text-[var(--foreground)] ${className}`}
    >
      <ChevronLeft className="h-4 w-4" aria-hidden="true" />
      <span>{label}</span>
    </Link>
  );
}

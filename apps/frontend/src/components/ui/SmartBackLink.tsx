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

export function BackLink({ href = "/notifications", children }: { href?: string; children: ReactNode }) {
  const searchParams = useSearchParams();
  const attentionOrigin = isAttentionOrigin(searchParams);
  const rawReturnTo = searchParams?.get("return_to")?.trim() ?? "";
  const safeReturnTo = rawReturnTo.startsWith("/") && !rawReturnTo.startsWith("//") ? rawReturnTo : null;
  const targetHref = attentionOrigin ? ATTENTION_RETURN_HREF : (safeReturnTo ?? href);
  const label = attentionOrigin
    ? ATTENTION_RETURN_LABEL
    : safeReturnTo?.includes("/statements/")
      ? "Back to Statement Review"
      : children;

  return (
    <Link href={targetHref} className="inline-flex items-center gap-1 text-sm text-muted hover:text-[var(--foreground)]">
      <ChevronLeft className="h-4 w-4" aria-hidden="true" />
      {label}
    </Link>
  );
}

export function AuditBackLink() {
  return <BackLink href="/audit">Back to Audit</BackLink>;
}

interface SmartBackLinkProps {
  fallbackHref?: string;
  fallbackLabel?: string;
  children?: ReactNode;
  className?: string;
}

export function SmartBackLink({
  fallbackHref = "/dashboard",
  fallbackLabel = "Back to Dashboard",
  children,
  className = "",
}: SmartBackLinkProps) {
  const searchParams = useSearchParams();
  const attentionOrigin = isAttentionOrigin(searchParams);
  const returnTo = searchParams ? searchParams.get("return_to") : null;
  const targetHref = attentionOrigin ? ATTENTION_RETURN_HREF : returnTo || fallbackHref;
  const label = attentionOrigin
    ? ATTENTION_RETURN_LABEL
    : children || (fallbackLabel && fallbackLabel !== "Back to Dashboard" ? fallbackLabel : returnTo ? "Back" : fallbackLabel);

  const handleClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
    if (attentionOrigin || returnTo) return;
    if (typeof window !== "undefined" && window.history.length > 2) {
      e.preventDefault();
      window.history.back();
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

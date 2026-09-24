"use client";

import Link from "next/link";
import { useMemo } from "react";
import { FileText, BookOpen, BarChart3 } from "lucide-react";
import type { DashboardOnboardingStatus } from "@/hooks/useDashboardData";

interface OnboardingGuideCardProps {
  onboardingStatus: DashboardOnboardingStatus | null;
}

export function OnboardingGuideCard({ onboardingStatus }: OnboardingGuideCardProps) {
  const isCoreFlowComplete =
    (onboardingStatus?.approvedStatementCount ?? 0) > 0 &&
    (onboardingStatus?.postedEntryCount ?? 0) > 0;
  const showOnboarding = onboardingStatus !== null && !isCoreFlowComplete;

  const onboardingSteps = useMemo(() => {
    const hasStatement = (onboardingStatus?.statementCount ?? 0) > 0;
    const hasApprovedOutput = isCoreFlowComplete;
    return [
      {
        label: "Upload a bank statement",
        href: "/upload",
        done: hasStatement,
        Icon: FileText,
      },
      {
        label: "Review and approve",
        href: "/notifications",
        done: hasApprovedOutput,
        Icon: BookOpen,
      },
      {
        label: "Read your reports",
        href: "/reports",
        done: hasApprovedOutput,
        Icon: BarChart3,
      },
    ];
  }, [isCoreFlowComplete, onboardingStatus]);

  if (!showOnboarding) {
    return null;
  }

  return (
    <section
      className="card p-5 mb-6 border-[var(--accent)]/40"
      aria-label="Getting started"
    >
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="text-xs text-muted uppercase tracking-wide">
            Getting started
          </p>
          <h2 className="text-lg font-semibold mt-1">
            Build your first accurate financial view
          </h2>
          <p className="text-sm text-muted mt-1">
            Upload, review, and approve a statement to replace this guide with real
            financial data.
          </p>
        </div>
        <div className="grid gap-2 sm:grid-cols-3 lg:min-w-[520px]">
          {onboardingSteps.map(({ label, href, done, Icon }) => (
            <Link
              key={href}
              href={href}
              className={`rounded-md border p-3 text-sm transition-colors ${
                done
                  ? "border-[var(--success)] bg-[var(--success-muted)]"
                  : "border-[var(--border)] hover:border-[var(--accent)] hover:bg-[var(--accent-muted)]"
              }`}
            >
              <div className="flex items-center gap-2">
                <Icon
                  className={
                    done
                      ? "h-4 w-4 text-[var(--success)]"
                      : "h-4 w-4 text-[var(--accent)]"
                  }
                  aria-hidden="true"
                />
                <span className="font-medium">{label}</span>
              </div>
              <p className="mt-1 text-xs text-muted">
                {done ? "Done" : "Next"}
              </p>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}

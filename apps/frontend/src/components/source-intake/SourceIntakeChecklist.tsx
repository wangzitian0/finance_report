"use client";

import Link from "next/link";
import {
  BriefcaseBusiness,
  Building2,
  ClipboardList,
  FileSpreadsheet,
  FileText,
  Home,
  Landmark,
  PencilLine,
  type LucideIcon,
} from "lucide-react";

import { Badge, type BadgeVariant } from "@/components/ui";
import type { PersonalReportPackageReadinessResponse } from "@/lib/types";

export const REQUIRED_REPORT_SOURCE_CLASSES = [
  "bank_statement",
  "brokerage_statement",
  "settlement_note",
  "esop_rsu_plan",
  "property_statement",
  "liability_statement",
  "csv_export",
  "manual_record",
] as const;

type ReportSourceClass = (typeof REQUIRED_REPORT_SOURCE_CLASSES)[number];

type SourceTrustSummary = NonNullable<
  PersonalReportPackageReadinessResponse["source_trust_summary"]
>;

interface SourceIntakeItem {
  id: ReportSourceClass;
  label: string;
  description: string;
  href: string;
  ctaLabel: string;
  defaultStatus: string;
  defaultVariant: BadgeVariant;
  icon: LucideIcon;
}

const SOURCE_INTAKE_ITEMS: SourceIntakeItem[] = [
  {
    id: "bank_statement",
    label: "Bank statements",
    description: "Bank PDF or CSV exports used for cash, income, expense, and transfer lines.",
    href: "/upload",
    ctaLabel: "Upload bank statements",
    defaultStatus: "Import supported",
    defaultVariant: "success",
    icon: Landmark,
  },
  {
    id: "brokerage_statement",
    label: "Brokerage statements",
    description: "Brokerage PDFs, CSVs, or structured payloads for holdings and investment activity.",
    href: "/upload",
    ctaLabel: "Upload brokerage statements",
    defaultStatus: "Import supported",
    defaultVariant: "success",
    icon: BriefcaseBusiness,
  },
  {
    id: "settlement_note",
    label: "Settlement notes",
    description: "Broker settlement evidence captured from the brokerage import flow.",
    href: "/upload",
    ctaLabel: "Capture settlement notes",
    defaultStatus: "Structured capture",
    defaultVariant: "info",
    icon: FileText,
  },
  {
    id: "esop_rsu_plan",
    label: "ESOP / RSU plans",
    description: "Employer grant or vesting documents for restricted compensation evidence.",
    href: "/portfolio/evidence?source_class=esop_rsu_plan",
    ctaLabel: "Add ESOP / RSU plans",
    defaultStatus: "Manual-trusted",
    defaultVariant: "info",
    icon: Building2,
  },
  {
    id: "property_statement",
    label: "Property statements",
    description: "Appraisals and property statements with an explicit valuation basis and as-of date.",
    href: "/portfolio/evidence?source_class=property_statement",
    ctaLabel: "Add property statements",
    defaultStatus: "Manual-trusted",
    defaultVariant: "info",
    icon: Home,
  },
  {
    id: "liability_statement",
    label: "Liability statements",
    description: "Loan, mortgage, credit-card, or other liability balances with source anchors.",
    href: "/portfolio/evidence?source_class=liability_statement",
    ctaLabel: "Add liability statements",
    defaultStatus: "Manual-trusted",
    defaultVariant: "info",
    icon: ClipboardList,
  },
  {
    id: "csv_export",
    label: "CSV exports",
    description: "Bank, brokerage, or wallet CSV exports parsed through the direct CSV path.",
    href: "/upload",
    ctaLabel: "Upload CSV exports",
    defaultStatus: "Deterministic proof",
    defaultVariant: "success",
    icon: FileSpreadsheet,
  },
  {
    id: "manual_record",
    label: "Manual records",
    description: "Balanced user-entered journal entries that remain explicitly manual in reports.",
    href: "/journal",
    ctaLabel: "Enter manual records",
    defaultStatus: "Manual-trusted",
    defaultVariant: "info",
    icon: PencilLine,
  },
];

function statusForSourceClass(
  item: SourceIntakeItem,
  summary?: SourceTrustSummary,
): { label: string; variant: BadgeVariant } {
  if (!summary) {
    return { label: item.defaultStatus, variant: item.defaultVariant };
  }
  if (summary.gap_source_classes.includes(item.id)) {
    return { label: "Needs source", variant: "warning" };
  }
  if (summary.manual_trusted_source_classes.includes(item.id)) {
    return { label: "Manual-trusted", variant: "info" };
  }
  if (summary.post_merge_llm_ocr_source_classes.includes(item.id)) {
    return { label: "Import supported", variant: "success" };
  }
  if (summary.deterministic_pr_source_classes.includes(item.id)) {
    return { label: "Deterministic proof", variant: "success" };
  }
  return { label: "Planned source", variant: "muted" };
}

export function SourceIntakeChecklist({
  sourceTrustSummary,
}: {
  sourceTrustSummary?: SourceTrustSummary;
}) {
  return (
    <section
      aria-label="Report source intake checklist"
      className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4"
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-base font-semibold">Source intake checklist</h2>
          <p className="mt-1 max-w-3xl text-sm text-muted">
            Add the source classes that make report readiness trustworthy. Manual evidence stays labelled manual-trusted.
          </p>
        </div>
        <Badge variant="muted">{SOURCE_INTAKE_ITEMS.length} source classes</Badge>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {SOURCE_INTAKE_ITEMS.map((item) => {
          const Icon = item.icon;
          const status = statusForSourceClass(item, sourceTrustSummary);
          return (
            <article
              key={item.id}
              data-testid={`source-intake-${item.id}`}
              className="flex min-h-[13rem] flex-col rounded-lg border border-[var(--border)] p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-3">
                  <span className="inline-flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-[var(--background-muted)]">
                    <Icon className="h-4 w-4 text-[var(--accent)]" aria-hidden="true" />
                  </span>
                  <div className="min-w-0">
                    <h3 className="text-sm font-semibold">{item.label}</h3>
                    <p className="mt-1 break-words font-mono text-[0.7rem] text-muted">
                      {item.id}
                    </p>
                  </div>
                </div>
                <Badge variant={status.variant}>{status.label}</Badge>
              </div>

              <p className="mt-3 flex-1 text-sm text-muted">{item.description}</p>

              <Link
                href={item.href}
                className="btn-secondary mt-4 inline-flex min-h-10 items-center justify-center text-sm"
              >
                {item.ctaLabel}
              </Link>
            </article>
          );
        })}
      </div>
    </section>
  );
}

"use client";

import { CheckCircle2, AlertTriangle, Scale, History, CreditCard, Link2 } from "lucide-react";
import type { InvariantStatus } from "@/lib/types";

interface InvariantChecksGridProps {
  equationInvariant: InvariantStatus;
  temporalInvariant: InvariantStatus;
  reconciliationInvariant: InvariantStatus;
  lineageInvariant: InvariantStatus;
}

export function InvariantChecksGrid({
  equationInvariant,
  temporalInvariant,
  reconciliationInvariant,
  lineageInvariant,
}: InvariantChecksGridProps) {
  const cards = [
    {
      invariant: equationInvariant,
      icon: Scale,
      fallbackName: "Accounting Equation Balance",
      proofFormula: "Assets = Liabilities + Equity (Δ = 0.00)",
    },
    {
      invariant: temporalInvariant,
      icon: History,
      fallbackName: "Temporal Continuity & Rollforward",
      proofFormula: "Consecutive Monthly Statements (Mn+1 ≡ Mn)",
    },
    {
      invariant: reconciliationInvariant,
      icon: CreditCard,
      fallbackName: "Reconciliation & Debt Clearance Purity",
      proofFormula: "Liability Settlement Purity (0 P&L Leakage)",
    },
    {
      invariant: lineageInvariant,
      icon: Link2,
      fallbackName: "Evidence Lineage & Traceability Anchors",
      proofFormula: "Immutable Source Document Anchoring",
    },
  ];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold">Invariant Proofs & Mathematical Health</h3>
        <span className="text-xs text-muted">Continuous real-time verification</span>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {cards.map(({ invariant, icon: Icon, fallbackName, proofFormula }) => {
          const isHealthy = invariant.is_healthy;
          return (
            <div
              key={fallbackName}
              className={`card flex flex-col justify-between p-5 transition-colors ${
                isHealthy
                  ? "border-[var(--border)] hover:border-[var(--success)]"
                  : "border-[var(--warning)] bg-[color-mix(in_srgb,var(--warning)_4%,transparent)]"
              }`}
            >
              <div>
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span
                      className={`flex h-8 w-8 items-center justify-center rounded-lg ${
                        isHealthy
                          ? "bg-[color-mix(in_srgb,var(--success)_15%,transparent)] text-[var(--success)]"
                          : "bg-[color-mix(in_srgb,var(--warning)_15%,transparent)] text-[var(--warning)]"
                      }`}
                    >
                      <Icon className="h-4 w-4" aria-hidden="true" />
                    </span>
                    <span className="text-sm font-semibold">
                      {invariant.name || fallbackName}
                    </span>
                  </div>

                  <span
                    className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-medium ${
                      isHealthy
                        ? "bg-[color-mix(in_srgb,var(--success)_15%,transparent)] text-[var(--success)]"
                        : "bg-[color-mix(in_srgb,var(--warning)_15%,transparent)] text-[var(--warning)]"
                    }`}
                  >
                    {isHealthy ? (
                      <>
                        <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
                        Verified
                      </>
                    ) : (
                      <>
                        <AlertTriangle className="h-3 w-3" aria-hidden="true" />
                        Attention
                      </>
                    )}
                  </span>
                </div>

                <p className="mt-3 text-xs font-mono text-muted">{proofFormula}</p>
                <p className="mt-1 text-sm font-medium">{invariant.summary}</p>
              </div>

              {invariant.detail && (
                <p className="mt-3 border-t border-[var(--border)] pt-2 text-xs text-muted">
                  {invariant.detail}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

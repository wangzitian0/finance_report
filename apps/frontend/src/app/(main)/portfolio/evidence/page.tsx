"use client";

/**
 * Guided evidence intake page (EPIC-011 AC11.9.6–AC11.9.9, issue #706).
 *
 * Hosts the shared {@link GuidedEvidenceForm} for ESOP/RSU, property, and
 * liability evidence. Persistence flows through the existing manual-valuation
 * API via the typed client inside the form component.
 */

import GuidedEvidenceForm from "@/components/assets/GuidedEvidenceForm";

export default function GuidedEvidencePage() {
  return (
    <div className="p-6">
      <div className="page-header">
        <h1 className="page-title">Guided evidence intake</h1>
        <p className="page-description">
          Record ESOP/RSU, property, and liability evidence with a structured
          valuation basis and source anchor. Manually entered values are clearly
          labelled manual-trusted across reports and the traceability appendix.
        </p>
      </div>
      <GuidedEvidenceForm />
    </div>
  );
}

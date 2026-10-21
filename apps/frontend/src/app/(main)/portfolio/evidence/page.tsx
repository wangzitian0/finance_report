"use client";

import { useSearchParams } from "next/navigation";

import GuidedEvidenceForm, { SOURCE_CLASS_CONFIGS, type EvidenceSourceClass } from "@/components/assets/GuidedEvidenceForm";

export default function GuidedEvidencePage() {
  const searchParams = useSearchParams();
  const raw = searchParams.get("source_class");
  const initialSourceClass = SOURCE_CLASS_CONFIGS.some((c) => c.value === raw) ? (raw as EvidenceSourceClass) : undefined;

  return (
    <div className="p-6">
      <div className="page-header">
        <h1 className="page-title">Guided evidence intake</h1>
        <p className="page-description">
          Record ESOP/RSU, property, and liability evidence with a structured valuation basis and source anchor. Manually entered values are clearly labelled manual-trusted across reports and the traceability appendix.
        </p>
      </div>
      <GuidedEvidenceForm initialSourceClass={initialSourceClass} />
    </div>
  );
}

"use client";

import { apiFetch } from "@/lib/api";
import type { Schemas } from "@/lib/api-schema";

export type ReviewedStatementEnvelopeRequest = Schemas["ReviewedStatementEnvelopeRequest"];
export type ReviewedStatementEnvelopeResponse = Schemas["ReviewedStatementEnvelopeResponse"];

/** Confirm an exact source-result version before it can be approved for posting. */
export function confirmStatementReviewEnvelope(
  statementId: string,
  request: ReviewedStatementEnvelopeRequest,
): Promise<ReviewedStatementEnvelopeResponse> {
  return apiFetch<ReviewedStatementEnvelopeResponse>(
    `/api/statements/${statementId}/review/envelope`,
    {
      method: "POST",
      body: JSON.stringify(request),
    },
  );
}

"use client";

import { apiOperation } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-schema";

export type ReviewedStatementEnvelopeRequest =
  Schemas["ReviewedStatementEnvelopeRequest"];
export type ReviewedStatementEnvelopeResponse =
  Schemas["ReviewedStatementEnvelopeResponse"];

/** Confirm an exact source-result version before it can be approved for posting. */
export function confirmStatementReviewEnvelope(
  statementId: string,
  request: ReviewedStatementEnvelopeRequest,
): Promise<ReviewedStatementEnvelopeResponse> {
  return apiOperation(
    "confirm_statement_review_envelope_statements__statement_id__review_envelope_post",
    { path: { statement_id: statementId }, body: request },
  );
}

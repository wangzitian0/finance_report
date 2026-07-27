"use client";

import { useEffect, useState } from "react";

import { apiOperationDownload } from "@/lib/api-client";

interface PdfPreviewPaneProps {
  /** Statement whose original document is streamed by the same-origin proxy. */
  statementId: string | null;
  /** Whether an uploaded document exists; avoids a guaranteed 404 fetch. */
  hasDocument?: boolean;
}

type PreviewState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; url: string }
  | { status: "error" };

/**
 * Renders the statement's original document inside the Stage 1 review.
 *
 * #963 / AC16.33.5: the document is fetched from the authenticated, same-origin
 * `/api/statements/{id}/document` endpoint (which carries the Bearer token) and
 * embedded as a `blob:` object URL. A raw iframe pointed at the cross-origin
 * object-storage URL is blocked by the CSP (`frame-src 'self' blob:`), and an
 * iframe GET cannot carry the bearer token anyway, so the blob approach is the
 * only one that both authenticates and satisfies the CSP.
 */
export function PdfPreviewPane({
  statementId,
  hasDocument = true,
}: PdfPreviewPaneProps) {
  const [state, setState] = useState<PreviewState>({ status: "idle" });

  useEffect(() => {
    if (!statementId || !hasDocument) {
      setState({ status: "idle" });
      return;
    }

    let objectUrl: string | null = null;
    let cancelled = false;
    setState({ status: "loading" });

    apiOperationDownload(
      "get_statement_document_statements__statement_id__document_get",
      { path: { statement_id: statementId } },
    )
      .then(({ blob }) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setState({ status: "ready", url: objectUrl });
      })
      .catch(() => {
        if (cancelled) return;
        setState({ status: "error" });
      });

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [statementId, hasDocument]);

  return (
    <div className="card flex flex-col min-h-0 h-full">
      <div className="card-header">
        <h3 className="text-sm font-medium">PDF Preview</h3>
      </div>
      <div className="flex-1 p-4 min-h-0">
        {state.status === "ready" ? (
          <iframe
            src={state.url}
            className="w-full h-full rounded border"
            title="Statement PDF preview"
            sandbox="allow-same-origin"
            referrerPolicy="no-referrer"
          >
            <p>
              PDF preview not available. Use the data table below to review
              statement content.
            </p>
          </iframe>
        ) : (
          <div className="w-full h-full flex items-center justify-center text-muted">
            {state.status === "loading"
              ? "Loading PDF preview…"
              : state.status === "error"
                ? "PDF preview could not be loaded"
                : "PDF preview not available"}
          </div>
        )}
      </div>
    </div>
  );
}

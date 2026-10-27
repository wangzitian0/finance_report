"use client";

import { useEffect, useState } from "react";

import { apiOperationDownload } from "@/lib/api-client";

interface PdfPreviewPaneProps {
  /** Statement whose original document is streamed by the same-origin proxy. */
  statementId: string | null;
  /** Whether an uploaded document exists; avoids a guaranteed 404 fetch. */
  hasDocument?: boolean;
}

/** The upload types that the browser shows inline (`StatementUploader` accepts PDF, PNG, JPG and CSV). */
const INLINE_PREVIEW_EXTENSIONS = new Set(["pdf", "png", "jpg", "jpeg"]);

/**
 * True when the source file has an inline preview (#2647). A CSV export has none: the
 * transaction table shows its content, so the page shows no empty preview panel for it.
 */
export function hasInlinePreview(filename: string | null | undefined): boolean {
  const extension = (filename ?? "").split(".").pop()?.toLowerCase() ?? "";
  return INLINE_PREVIEW_EXTENSIONS.has(extension);
}

type PreviewState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; url: string; filename: string }
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
export function PdfPreviewPane({ statementId, hasDocument = true }: PdfPreviewPaneProps) {
  const [state, setState] = useState<PreviewState>({ status: "idle" });

  useEffect(() => {
    if (!statementId || !hasDocument) {
      setState({ status: "idle" });
      return;
    }
    let objectUrl: string | null = null;
    let cancelled = false;
    setState({ status: "loading" });

    apiOperationDownload("get_statement_document_statements__statement_id__document_get", { path: { statement_id: statementId } })
      .then(({ blob, filename }) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setState({ status: "ready", url: objectUrl, filename: filename || "statement.pdf" });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error" });
      });

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [statementId, hasDocument]);

  const isExpanded = state.status === "ready" || state.status === "loading";

  return (
    <div className={`card flex flex-col min-h-0 ${isExpanded ? "h-full" : "h-auto"}`}>
      <div className="card-header flex items-center justify-between">
        <h3 className="text-sm font-medium">PDF Preview</h3>
        {state.status === "ready" && (
          <div className="flex items-center gap-3">
            <a href={state.url} download={state.filename} data-testid="pdf-download-link" className="text-xs text-[var(--accent)] hover:underline flex items-center gap-1">
              <span>Download PDF</span>
            </a>
            <a href={state.url} target="_blank" rel="noopener noreferrer" className="text-xs text-[var(--accent)] hover:underline flex items-center gap-1">
              <span>Open in new tab</span>
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
            </a>
          </div>
        )}
      </div>
      <div className={isExpanded ? "flex-1 p-4 min-h-0" : "p-4"}>
        {state.status === "ready" ? (
          /* #2107: Do not declare sandbox on the PDF iframe. In Chromium, any sandbox
             attribute disables browser plugins including internal PDFium, rendering
             ERR_BLOCKED_BY_CLIENT ("This page has been blocked by Chromium"). The blob URL
             is safe as it is fetched via authenticated same-origin API and governed by
             frame-src 'self' blob: CSP. */
          <iframe src={state.url} className="w-full h-full rounded border" title="Statement PDF preview" referrerPolicy="no-referrer" />
        ) : state.status === "error" ? (
          <div data-testid="pdf-fallback-container" className="w-full flex flex-col items-center justify-center gap-2 text-muted text-center py-4">
            <p className="text-sm">PDF preview could not be loaded</p>
            <p className="text-xs text-muted">The preview could not be rendered inline.</p>
          </div>
        ) : (
          <div className="w-full flex items-center justify-center text-muted py-4 text-sm">
            {state.status === "loading" ? "Loading PDF preview…" : "PDF preview not available"}
          </div>
        )}
      </div>
    </div>
  );
}

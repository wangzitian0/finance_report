"use client";

import { useEffect, useState } from "react";

import Sheet from "@/components/ui/Sheet";
import { apiFetch } from "@/lib/api";
import { lineageUrl, nodeLabel, type LineageAnchor } from "@/lib/lineage";
import type { EvidenceLineageResponse } from "@/lib/types";

interface LineagePanelState {
  isLoading: boolean;
  error: string | null;
  response: EvidenceLineageResponse | null;
}

const EMPTY_STATE: LineagePanelState = { isLoading: false, error: null, response: null };

export interface LineagePanelProps {
  /** Heading for the drawer (e.g. the report line / transaction description). */
  title: string;
  /** Lineage anchor to resolve; when null the panel is closed. */
  anchor: LineageAnchor | null;
  onClose: () => void;
}

/**
 * Reusable evidence-lineage drawer (EPIC-022 AC22.3.4). Given a lineage anchor
 * it fetches `/api/evidence/lineage` and renders the upstream/downstream chain
 * (ledger line → bank statement transaction → atomic fact → source document),
 * surfacing blockers and a graceful empty state when nothing is linked.
 */
export function LineagePanel({ title, anchor, onClose }: LineagePanelProps) {
  const [state, setState] = useState<LineagePanelState>(EMPTY_STATE);
  const anchorKey = anchor ? `${anchor.entity_type}:${anchor.entity_id}:${anchor.node_kind ?? ""}` : null;

  useEffect(() => {
    if (!anchor) {
      setState(EMPTY_STATE);
      return;
    }
    let active = true;
    setState({ isLoading: true, error: null, response: null });
    apiFetch<EvidenceLineageResponse>(lineageUrl(anchor))
      .then((response) => {
        if (active) setState({ isLoading: false, error: null, response });
      })
      .catch((err: unknown) => {
        if (active) {
          setState({
            isLoading: false,
            error: err instanceof Error ? err.message : "Failed to load lineage",
            response: null,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [anchor, anchorKey]);

  const { isLoading, error, response } = state;

  return (
    <Sheet isOpen={anchor !== null} onClose={onClose} title="Source lineage" width="max-w-lg">
      <div className="space-y-4">
        <p className="text-sm font-medium break-words">{title}</p>

        {isLoading && (
          <p className="text-sm text-muted" role="status">
            Loading source lineage…
          </p>
        )}

        {error && <div className="alert-error text-sm">{error}</div>}

        {!isLoading && !error && response && (
          <>
            {response.blockers.length > 0 && (
              <div className="space-y-2" aria-label="Lineage blockers">
                {response.blockers.map((blocker) => (
                  <div key={blocker.code} className="alert-warning text-sm">
                    {blocker.message}
                  </div>
                ))}
              </div>
            )}

            {response.nodes.length === 0 ? (
              <p className="text-sm text-muted">No source records are linked to this amount yet.</p>
            ) : (
              <ol className="space-y-2" aria-label="Lineage nodes">
                {response.nodes.map((node) => (
                  <li
                    key={node.id}
                    className="rounded-md border border-[var(--border)] bg-[var(--background-muted)]/40 p-3 text-sm"
                  >
                    <div className="font-medium">{node.node_kind.replace(/_/g, " ")}</div>
                    <div className="mt-1 break-all font-mono text-xs text-muted">{nodeLabel(node)}</div>
                  </li>
                ))}
              </ol>
            )}
          </>
        )}
      </div>
    </Sheet>
  );
}
